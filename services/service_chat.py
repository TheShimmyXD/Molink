"""Responsabilidad unica: pasar mensajes de chat al otro equipo con acuse de recibo.

Viajan por un subsistema SSH propio (CHAT_SUBSYSTEM) en la misma conexion de
los comandos y los archivos, asi que solo los equipos emparejados llegan aqui.
Cada mensaje es una linea JSON {"id": ..., "text": ...} y el que recibe
contesta {"ack": id} cuando ya lo entrego a la app. Una linea mas larga que
MAX_LINE, que no sea JSON o sin sus campos cierra el canal: el otro lado no
habla Molink.

El texto de un mensaje nunca va a un log: solo su tamano.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import asyncssh

from services.service_ssh_server import PEER_KEY_INFO

logger = logging.getLogger(__name__)

CHAT_SUBSYSTEM = "molink-chat"
MAX_LINE = 64 * 1024
READ_CHUNK = 16 * 1024
ACK_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class ChatMessage:
    """Un mensaje que llego; peer lo pone service_link con el nombre emparejado."""

    message_id: str
    text: str
    received_at: float
    peer_key: bytes = b""
    peer: str = ""


MessageCallback = Callable[[ChatMessage], None]


class ChatProtocolError(ValueError):
    """El otro lado mando algo que no es un mensaje de Molink."""


def encode_line(payload: dict) -> bytes:
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
    if len(line) > MAX_LINE:
        raise ValueError(f"El mensaje pasa de {MAX_LINE // 1024} KiB")
    return line


def decode_line(line: bytes, keys: tuple[str, ...]) -> dict:
    """La linea como dict con keys de tipo str; ChatProtocolError si no lo es."""
    if len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise ChatProtocolError("Linea demasiado larga o cortada")
    try:
        payload = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChatProtocolError("No es JSON") from exc
    if not isinstance(payload, dict) or not all(isinstance(payload.get(k), str) for k in keys):
        raise ChatProtocolError("Faltan campos")
    return payload


class _LineReader:
    """Lineas con su fin; b"" al cerrar. Corta en MAX_LINE para no llenar la memoria."""

    def __init__(self, reader: asyncssh.SSHReader):
        self._reader = reader
        self._buffer = b""

    async def next(self) -> bytes:
        while (end := self._buffer.find(b"\n")) < 0:
            if len(self._buffer) > MAX_LINE:
                raise ChatProtocolError("Linea demasiado larga")
            chunk = await self._reader.read(READ_CHUNK)
            if not chunk:
                if self._buffer:
                    raise ChatProtocolError("Linea cortada")
                return b""
            self._buffer += chunk
        line, self._buffer = self._buffer[: end + 1], self._buffer[end + 1 :]
        return line


async def serve_chat(process: asyncssh.SSHServerProcess, on_message: MessageCallback) -> None:
    """Lado que recibe: entrega cada mensaje a on_message y contesta su acuse."""
    conn = process.channel.get_connection()
    peer_key = conn.get_extra_info(PEER_KEY_INFO, b"")
    lines = _LineReader(process.stdin)
    try:
        while line := await lines.next():
            payload = decode_line(line, ("id", "text"))
            message = ChatMessage(payload["id"], payload["text"], time.time(), peer_key)
            try:
                on_message(message)
            except Exception:
                # Sin acuse: el que envia lo ve como no entregado.
                logger.exception("Fallo la entrega de un mensaje a la app")
                continue
            logger.info("Mensaje recibido de %s bytes", len(line))
            process.stdout.write(encode_line({"ack": message.message_id}))
    except ChatProtocolError as exc:
        logger.warning("Canal de chat cerrado: %s", exc)
        process.exit(1)
        return
    except (asyncssh.Error, OSError, asyncio.CancelledError):
        return
    process.exit(0)


@dataclass
class ChatChannel:
    """Lado que envia: un canal abierto al otro equipo; send espera el acuse."""

    process: asyncssh.SSHClientProcess
    _waiting: dict[str, asyncio.Future] = field(default_factory=dict)
    _reader: asyncio.Task | None = None

    @classmethod
    async def open(cls, conn: asyncssh.SSHClientConnection) -> ChatChannel:
        process = await conn.create_process(subsystem=CHAT_SUBSYSTEM, encoding=None)
        channel = cls(process)
        channel._reader = asyncio.ensure_future(channel._read_acks())
        return channel

    @property
    def closed(self) -> bool:
        return self._reader is None or self._reader.done()

    async def _read_acks(self) -> None:
        lines = _LineReader(self.process.stdout)
        try:
            while line := await lines.next():
                ack = decode_line(line, ("ack",))["ack"]
                waiter = self._waiting.pop(ack, None)
                if waiter is not None and not waiter.done():
                    waiter.set_result(None)
        except (ChatProtocolError, asyncssh.Error, OSError) as exc:
            logger.warning("Canal de chat perdido: %s", type(exc).__name__)
        finally:
            for waiter in self._waiting.values():
                if not waiter.done():
                    waiter.set_exception(ConnectionError("Se cerro el canal de chat"))
            self._waiting.clear()

    async def send(
        self, text: str, timeout: float = ACK_TIMEOUT_S, message_id: str | None = None
    ) -> str:
        """Envia text y devuelve su id cuando el otro lo acusa.

        message_id se da al reintentar el mismo mensaje por otro canal.
        ValueError si pasa de MAX_LINE; ConnectionError si el canal se cerro;
        TimeoutError si no llega el acuse.
        """
        message_id = message_id or uuid.uuid4().hex
        line = encode_line({"id": message_id, "text": text})
        if self.closed:
            raise ConnectionError("Se cerro el canal de chat")
        waiter = asyncio.get_running_loop().create_future()
        self._waiting[message_id] = waiter
        try:
            self.process.stdin.write(line)
            await asyncio.wait_for(waiter, timeout)
        finally:
            self._waiting.pop(message_id, None)
        logger.info("Mensaje enviado de %s bytes", len(line))
        return message_id

    async def close(self) -> None:
        with contextlib.suppress(asyncssh.Error, OSError):
            self.process.stdin.write_eof()
        self.process.close()
        if self._reader is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(self._reader, ACK_TIMEOUT_S)
