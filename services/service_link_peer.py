"""Responsabilidad unica: lo que la sesion hace con un equipo emparejado.

Conectarse a el, correr un comando, enviarle un archivo y chatear. LinkSession
(service_link) hereda de PeerActions y le da identity y los equipos vistos
(_seen); aqui solo se traduce cada fallo a un LinkError que la UI explica.
El chat deja abierta una conexion por equipo y la reabre si se cayo.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncssh

    from services.service_chat import ChatChannel
    from services.service_discovery import Peer
    from services.service_identity import DeviceIdentity
    from services.service_ssh_client import OutputCallback
    from services.service_transfer import ProgressCallback

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 10.0


class LinkError(Exception):
    """Algo que se le explica al usuario: que paso y que hacer."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


class PeerActions:
    """Acciones sobre los equipos emparejados; LinkSession pone los atributos."""

    identity: DeviceIdentity
    _seen: dict[str, Peer]
    # Por nombre: la conexion y el canal de chat abiertos con ese equipo.
    _chats: dict[str, tuple[asyncssh.SSHClientConnection, ChatChannel]]
    _chat_locks: dict[str, asyncio.Lock]

    def paired_names(self) -> list[str]:
        from services.service_paired import load_paired

        return [peer.name for peer in load_paired(self.identity.data_dir)]

    async def forget(self, name: str) -> bool:
        """Quita al equipo de paired.json: ya no puede entrar ni se le conecta."""
        from services.service_paired import remove_paired

        await self._drop_chat(name)
        return remove_paired(self.identity.data_dir, name)

    def _peer_by_key(self, public_data: bytes) -> str:
        import asyncssh

        from services.service_paired import load_paired

        for record in load_paired(self.identity.data_dir):
            if asyncssh.import_public_key(record.user_key).public_data == public_data:
                return record.name
        return ""

    async def _connect(self, name: str):
        """Conexion SSH al equipo emparejado name, que la ultima busqueda vio en la red."""
        import asyncssh

        from services.service_paired import load_paired
        from services.service_ssh_client import connect_peer

        record = next((p for p in load_paired(self.identity.data_dir) if p.name == name), None)
        if record is None:
            raise LinkError(f"{name} ya no está emparejado.", "Empareja de nuevo en 'Emparejar'.")
        peer = self._seen.get(name)
        if peer is None:
            raise LinkError(
                f"{name} no está en la red.", "Abre Molink allá y espera unos segundos."
            )
        host_key = asyncssh.import_public_key(record.host_key)
        try:
            return await asyncio.wait_for(
                connect_peer(peer.address, peer.port, self.identity.user_key, host_key),
                CONNECT_TIMEOUT_S,
            )
        except asyncssh.PermissionDenied as exc:
            raise LinkError(
                f"{name} no tiene emparejado a este equipo.", "Allá, empareja de nuevo."
            ) from exc
        except asyncssh.HostKeyNotVerifiable as exc:
            raise LinkError(
                f"El equipo en {peer.address} no es el {name} emparejado.",
                "Olvídalo en 'Emparejar' y empareja de nuevo.",
            ) from exc
        except (asyncssh.Error, OSError, TimeoutError) as exc:
            raise LinkError(
                f"No se pudo conectar a {peer.address}:{peer.port}.",
                "¿Molink está abierto allá? Si lo está, revisa su cortafuegos.",
            ) from exc

    async def run(
        self, name: str, command: str, on_output: OutputCallback, stdin: bytes = b""
    ) -> int | None:
        """Corre command en el equipo emparejado name y pasa la salida en vivo.

        stdin va al comando y luego fin de entrada (la contrasena de sudo).
        on_output se llama en el hilo del bucle. Devuelve el codigo de
        salida (None si el otro no lo dio). Cancelar la tarea cierra el canal y
        el servidor termina el comando alla.
        """
        import asyncssh

        from services.service_ssh_client import stream_command

        conn = await self._connect(name)
        try:
            async with conn:
                return await stream_command(conn, command, on_output, stdin)
        except (asyncssh.Error, OSError) as exc:
            raise LinkError(
                f"Se perdió la conexión con {name}.", "Revisa la red y vuelve a correrlo."
            ) from exc

    async def send(self, name: str, path: Path, on_progress: ProgressCallback) -> str:
        """Envia el archivo path al equipo emparejado name; devuelve el nombre con que llego.

        on_progress(enviados, total) se llama en el hilo del bucle. Cancelar la
        tarea corta el envio y borra el .part alla.
        """
        import asyncssh

        from services.service_transfer import STALL_S, TransferStalled, send_file

        if not path.is_file():
            raise LinkError(f"No se encontró {path.name}.", "Elige el archivo de nuevo.")
        conn = await self._connect(name)
        try:
            async with conn:
                return await send_file(conn, path, on_progress)
        except asyncssh.ChannelOpenError as exc:
            raise LinkError(
                f"{name} no recibe archivos.", "Actualiza Molink allá a la misma versión."
            ) from exc
        except asyncssh.SFTPPermissionDenied as exc:
            raise LinkError(
                f"{name} rechazó el archivo.", "Revisa que su carpeta de llegada se pueda escribir."
            ) from exc
        except TransferStalled as exc:
            raise LinkError(
                f"El envío a {name} se detuvo: no avanzó en {STALL_S:.0f} s.",
                "Revisa la wifi de los dos equipos y vuelve a enviarlo.",
            ) from exc
        except FileExistsError as exc:
            raise LinkError(
                f"Allá ya hay demasiados archivos llamados {path.name}.",
                "Cámbiale el nombre y vuelve a enviarlo.",
            ) from exc
        except (asyncssh.Error, OSError) as exc:
            raise LinkError(
                f"Se perdió la conexión con {name}.", "Revisa la red y vuelve a enviarlo."
            ) from exc

    async def say(self, name: str, text: str) -> str:
        """Envia un mensaje de chat a name y devuelve su id cuando alla lo acusan.

        Si el canal guardado ya se cerro (el otro reinicio la app, la wifi se
        corto) se reabre una vez con el mismo id: el que recibe puede descartar
        un repetido por id.
        """
        from services.service_chat import ACK_TIMEOUT_S, MAX_LINE

        message_id = uuid.uuid4().hex
        for attempt in (1, 2):
            channel = await self._chat_channel(name)
            try:
                return await channel.send(text, ACK_TIMEOUT_S, message_id)
            except ValueError as exc:
                raise LinkError(
                    f"El mensaje pasa de {MAX_LINE // 1024} KiB.", "Envíalo como archivo."
                ) from exc
            except TimeoutError as exc:
                await self._drop_chat(name)
                raise LinkError(
                    f"{name} no confirmó el mensaje.", "Revisa la red y vuelve a enviarlo."
                ) from exc
            except ConnectionError as exc:
                await self._drop_chat(name)
                if attempt == 2:
                    raise LinkError(
                        f"Se perdió la conexión con {name}.", "Revisa la red y vuelve a enviarlo."
                    ) from exc
        raise AssertionError("inalcanzable")

    async def _chat_channel(self, name: str) -> ChatChannel:
        """El canal de chat abierto con name; lo abre si no hay o se cerro."""
        import asyncssh

        from services.service_chat import ChatChannel

        lock = self._chat_locks.setdefault(name, asyncio.Lock())
        async with lock:
            current = self._chats.get(name)
            if current is not None and not current[1].closed:
                return current[1]
            await self._drop_chat(name)
            conn = await self._connect(name)
            try:
                channel = await ChatChannel.open(conn)
            except (asyncssh.Error, OSError) as exc:
                conn.close()
                raise LinkError(
                    f"{name} no recibe mensajes.", "Actualiza Molink allá a la misma versión."
                ) from exc
            self._chats[name] = (conn, channel)
            return channel

    async def _drop_chat(self, name: str) -> None:
        current = self._chats.pop(name, None)
        if current is None:
            return
        conn, channel = current
        with contextlib.suppress(Exception):
            await channel.close()
        conn.close()
        with contextlib.suppress(Exception):
            await conn.wait_closed()

    async def _close_chats(self) -> None:
        for name in list(self._chats):
            await self._drop_chat(name)
        self._chat_locks.clear()
