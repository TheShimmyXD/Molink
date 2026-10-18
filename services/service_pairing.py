"""Emparejamiento con SPAKE2: el codigo de 6 digitos autentica las llaves.

Un equipo muestra el codigo (shower, SPAKE2_A) y el otro lo escribe (joiner,
SPAKE2_B). El codigo nunca viaja: con SPAKE2 los dos llegan a la misma llave
solo si escribieron el mismo, y cada intento prueba un solo codigo. Con esa
llave se firma (HMAC) lo que cada uno manda: su nombre y sus dos llaves
publicas. Un intermediario sin el codigo no puede cambiarlas sin que se note.

Cuatro mensajes, sobre cualquier canal de bytes (Channel):
    1. joiner -> shower: SPAKE2 del joiner
    2. shower -> joiner: SPAKE2 del shower + sus llaves + HMAC
    3. joiner -> shower: sus llaves + HMAC
    4. shower -> joiner: acuse con HMAC; solo entonces el joiner guarda al otro

Nada de esto escribe el codigo en un log.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from spake2 import SPAKE2_A, SPAKE2_B, SPAKEError

from logic._00_logic_pairing import (
    WINDOW_SECONDS,
    PairingState,
    PairingWindow,
    new_code,
    normalize_code,
)
from services.service_paired import PeerRecord

logger = logging.getLogger(__name__)

PROTOCOL = b"molink-pair-v1"
VERSION = 1
ID_SHOWER = b"molink-shows-code"
ID_JOINER = b"molink-types-code"
MAX_FRAME = 8192
STEP_TIMEOUT = 30.0


class PairingFailure(StrEnum):
    WRONG_CODE = "wrong_code"
    EXPIRED = "expired"
    LOCKED = "locked"
    CLOSED = "closed"
    PROTOCOL = "protocol"
    TIMEOUT = "timeout"


_STATE_FAILURE = {
    PairingState.EXPIRED: PairingFailure.EXPIRED,
    PairingState.LOCKED: PairingFailure.LOCKED,
    PairingState.CLOSED: PairingFailure.CLOSED,
    PairingState.PAIRED: PairingFailure.CLOSED,
}


class PairingError(Exception):
    def __init__(self, reason: PairingFailure):
        super().__init__(reason.value)
        self.reason = reason


class ChannelClosed(Exception):
    """El otro lado cerro el canal antes de tiempo."""


class Channel(Protocol):
    async def send(self, data: bytes) -> None: ...

    async def recv(self) -> bytes: ...


class StreamChannel:
    """Marcos de 4 bytes de largo + contenido sobre un par de streams de asyncio."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        timeout: float = STEP_TIMEOUT,
    ):
        self._reader = reader
        self._writer = writer
        self._timeout = timeout

    async def send(self, data: bytes) -> None:
        if len(data) > MAX_FRAME:
            raise PairingError(PairingFailure.PROTOCOL)
        self._writer.write(len(data).to_bytes(4, "big") + data)
        await self._writer.drain()

    async def recv(self) -> bytes:
        try:
            header = await asyncio.wait_for(self._reader.readexactly(4), self._timeout)
            size = int.from_bytes(header, "big")
            if size > MAX_FRAME:
                raise PairingError(PairingFailure.PROTOCOL)
            return await asyncio.wait_for(self._reader.readexactly(size), self._timeout)
        except asyncio.IncompleteReadError as exc:
            raise ChannelClosed from exc
        except TimeoutError as exc:
            raise PairingError(PairingFailure.TIMEOUT) from exc


class PairingSession:
    """Lado que muestra el codigo: el codigo vive solo aqui, en memoria."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        randbelow: Callable[[int], int] = secrets.randbelow,
        window: float = WINDOW_SECONDS,
    ):
        self._clock = clock
        self.code = new_code(randbelow)
        self.window = PairingWindow(clock(), window)

    def now(self) -> float:
        return self._clock()

    def state(self) -> PairingState:
        return self.window.state(self._clock())


# -- Mensajes ---------------------------------------------------


def _encode(**fields: bytes | int | str) -> bytes:
    data = {
        key: base64.b64encode(value).decode("ascii") if isinstance(value, bytes) else value
        for key, value in fields.items()
    }
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def _decode(data: bytes) -> dict:
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PairingError(PairingFailure.PROTOCOL) from exc
    if not isinstance(message, dict):
        raise PairingError(PairingFailure.PROTOCOL)
    return message


def _field(message: dict, name: str) -> bytes:
    try:
        return base64.b64decode(message[name], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise PairingError(PairingFailure.PROTOCOL) from exc


def _raise_if_error(message: dict) -> None:
    if "error" in message:
        try:
            reason = PairingFailure(message["error"])
        except ValueError:
            reason = PairingFailure.PROTOCOL
        raise PairingError(reason)


async def _recv(channel: Channel, closed_reason: PairingFailure) -> dict:
    try:
        return _decode(await channel.recv())
    except ChannelClosed as exc:
        raise PairingError(closed_reason) from exc


async def _send_error(channel: Channel, reason: PairingFailure) -> None:
    with contextlib.suppress(ConnectionError, ChannelClosed):
        await channel.send(_encode(error=reason.value))


# -- Llaves y firmas ---------------------------------------------


def _framed(*parts: bytes) -> bytes:
    return b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def _derive(shared: bytes, msg_shower: bytes, msg_joiner: bytes) -> tuple[bytes, bytes, bytes]:
    """Hash de los dos mensajes y una llave HMAC por sentido."""
    transcript = hashlib.sha256(_framed(PROTOCOL, msg_shower, msg_joiner)).digest()

    def key(label: bytes) -> bytes:
        hkdf = HKDF(hashes.SHA256(), 32, salt=transcript, info=PROTOCOL + b"/" + label)
        return hkdf.derive(shared)

    return transcript, key(b"shower"), key(b"joiner")


def _mac(key: bytes, transcript: bytes, label: bytes, payload: bytes) -> bytes:
    return hmac.new(key, _framed(transcript, label, payload), hashlib.sha256).digest()


def _verify(expected: bytes, received: bytes) -> bool:
    return hmac.compare_digest(expected, received)


def _payload(peer: PeerRecord) -> bytes:
    data = {"name": peer.name, "user_key": peer.user_key, "host_key": peer.host_key}
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _peer_from(payload: bytes, own: PeerRecord) -> PeerRecord:
    try:
        data = json.loads(payload.decode("utf-8"))
        peer = PeerRecord.build(data["name"], data["user_key"], data["host_key"])
    except Exception as exc:
        raise PairingError(PairingFailure.PROTOCOL) from exc
    if peer.host_key == own.host_key or peer.user_key == own.user_key:
        raise PairingError(PairingFailure.PROTOCOL)  # el mismo equipo de los dos lados
    return peer


# -- Los dos lados -----------------------------------------------


async def pair_as_shower(session: PairingSession, channel: Channel, own: PeerRecord) -> PeerRecord:
    """Atiende un intento del otro equipo; devuelve sus llaves si el codigo coincide."""
    first = await _recv(channel, PairingFailure.PROTOCOL)
    if first.get("v") != VERSION:
        await _send_error(channel, PairingFailure.PROTOCOL)
        raise PairingError(PairingFailure.PROTOCOL)
    state = session.window.start_attempt(session.now())
    if state is not PairingState.OPEN:
        await _send_error(channel, _STATE_FAILURE[state])
        raise PairingError(_STATE_FAILURE[state])
    paired = False
    try:
        spake = SPAKE2_A(session.code.encode("ascii"), idA=ID_SHOWER, idB=ID_JOINER)
        msg_shower = spake.start()
        msg_joiner = _field(first, "spake")
        try:
            shared = spake.finish(msg_joiner)
        except SPAKEError as exc:
            raise PairingError(PairingFailure.PROTOCOL) from exc
        transcript, k_shower, k_joiner = _derive(shared, msg_shower, msg_joiner)
        own_payload = _payload(own)
        mac = _mac(k_shower, transcript, b"payload", own_payload)
        await channel.send(_encode(spake=msg_shower, payload=own_payload, mac=mac))

        third = await _recv(channel, PairingFailure.WRONG_CODE)
        _raise_if_error(third)
        peer_payload = _field(third, "payload")
        if not _verify(_mac(k_joiner, transcript, b"payload", peer_payload), _field(third, "mac")):
            await _send_error(channel, PairingFailure.WRONG_CODE)
            raise PairingError(PairingFailure.WRONG_CODE)
        peer = _peer_from(peer_payload, own)
        if session.window.finish_attempt(session.now(), success=True) is not PairingState.PAIRED:
            await _send_error(channel, PairingFailure.EXPIRED)
            raise PairingError(PairingFailure.EXPIRED)
        paired = True
        await channel.send(_encode(ack=_mac(k_shower, transcript, b"ack", peer_payload)))
        logger.info("Emparejamiento aceptado: %s", peer.name)
        return peer
    finally:
        if not paired:
            session.window.finish_attempt(session.now(), success=False)
            logger.info(
                "Intento de emparejamiento fallido; quedan %s", session.window.attempts_left
            )


async def pair_as_joiner(code: str, channel: Channel, own: PeerRecord) -> PeerRecord:
    """Prueba el codigo que el usuario escribio; devuelve las llaves del otro equipo."""
    spake = SPAKE2_B(normalize_code(code).encode("ascii"), idA=ID_SHOWER, idB=ID_JOINER)
    msg_joiner = spake.start()
    await channel.send(_encode(v=VERSION, spake=msg_joiner))

    second = await _recv(channel, PairingFailure.PROTOCOL)
    _raise_if_error(second)
    msg_shower = _field(second, "spake")
    try:
        shared = spake.finish(msg_shower)
    except SPAKEError as exc:
        raise PairingError(PairingFailure.PROTOCOL) from exc
    transcript, k_shower, k_joiner = _derive(shared, msg_shower, msg_joiner)
    peer_payload = _field(second, "payload")
    if not _verify(_mac(k_shower, transcript, b"payload", peer_payload), _field(second, "mac")):
        await _send_error(channel, PairingFailure.WRONG_CODE)
        raise PairingError(PairingFailure.WRONG_CODE)
    peer = _peer_from(peer_payload, own)

    own_payload = _payload(own)
    await channel.send(
        _encode(payload=own_payload, mac=_mac(k_joiner, transcript, b"payload", own_payload))
    )
    fourth = await _recv(channel, PairingFailure.PROTOCOL)
    _raise_if_error(fourth)
    if not _verify(_mac(k_shower, transcript, b"ack", own_payload), _field(fourth, "ack")):
        raise PairingError(PairingFailure.PROTOCOL)
    logger.info("Emparejado con %s", peer.name)
    return peer
