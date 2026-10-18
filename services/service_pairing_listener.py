"""Emparejamiento por la red: el puerto 47821 abierto solo durante la ventana.

El equipo que muestra el codigo llama a open_pairing_window: escucha en la IP
de la red local (nunca 0.0.0.0), corta un origen de fuera de la subred antes
de leer nada y deja de escuchar al emparejar, al caducar la ventana, al
gastarse los intentos o al cancelar. Atiende un intento a la vez. El que
escribe el codigo llama a join_pairing. Los dos guardan al otro en
paired.json; el codigo no sale de memoria ni va a un log.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from logic._00_logic_pairing import WINDOW_SECONDS, PairingState, normalize_code
from services.service_paired import PeerRecord, add_paired
from services.service_pairing import (
    STEP_TIMEOUT,
    ChannelClosed,
    PairingError,
    PairingSession,
    StreamChannel,
    pair_as_joiner,
    pair_as_shower,
)
from services.service_ssh_server import DEFAULT_PORT, check_listen_host, is_allowed_origin

if TYPE_CHECKING:
    from pathlib import Path

    from services.service_identity import DeviceIdentity

logger = logging.getLogger(__name__)

PAIRING_PORT = DEFAULT_PORT + 1


def own_record(identity: DeviceIdentity) -> PeerRecord:
    """Lo que este equipo le manda al otro: su nombre y sus dos llaves publicas."""
    return PeerRecord.build(
        identity.name,
        identity.user_key.export_public_key().decode("ascii"),
        identity.host_key.export_public_key().decode("ascii"),
    )


class PairingListener:
    """Ventana abierta en la red; wait() da el equipo emparejado o None."""

    def __init__(self, session: PairingSession, own: PeerRecord, data_dir: Path, network: str):
        self.session = session
        self._own = own
        self._data_dir = data_dir
        self._network = network
        self._lock = asyncio.Lock()
        self._done: asyncio.Future[PeerRecord | None] = asyncio.get_running_loop().create_future()
        self._writers: set[asyncio.StreamWriter] = set()
        self._server: asyncio.Server | None = None
        self._timer: asyncio.TimerHandle | None = None
        self.port = 0

    async def _start(self, host: str, port: int) -> None:
        self._server = await asyncio.start_server(self._handle, host, port)
        self.port = self._server.sockets[0].getsockname()[1]
        remaining = self.session.window.remaining(self.session.now())
        self._timer = asyncio.get_running_loop().call_later(remaining, self._finish, None)
        logger.info("Ventana de emparejamiento abierta en el puerto %s", self.port)

    def remaining(self) -> float:
        return self.session.window.remaining(self.session.now())

    def _finish(self, peer: PeerRecord | None) -> None:
        """Deja de escuchar en cuanto la ventana termina, por la razon que sea."""
        if self._done.done():
            return
        self._done.set_result(peer)
        if self._server is not None:
            self._server.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            if not is_allowed_origin(writer.get_extra_info("peername")[0], self._network):
                logger.warning("Emparejamiento rechazado: origen fuera de la red local")
                return
            async with self._lock:
                if self._done.done():
                    return
                try:
                    peer = await pair_as_shower(
                        self.session, StreamChannel(reader, writer), self._own
                    )
                except (PairingError, ChannelClosed, ConnectionError) as exc:
                    logger.info("Intento de emparejamiento rechazado: %s", exc)
                    if self.session.state() is not PairingState.OPEN:
                        self._finish(None)
                    return
                add_paired(self._data_dir, peer)
                self._finish(peer)
        finally:
            self._writers.discard(writer)
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    async def wait(self) -> PeerRecord | None:
        """Espera a que la ventana termine; el puerto queda cerrado al volver."""
        try:
            return await asyncio.shield(self._done)
        finally:
            await self.close()

    async def close(self) -> None:
        """Cancela la ventana si sigue abierta y corta los intentos en curso."""
        self.session.window.close()
        self._finish(None)
        if self._timer is not None:
            self._timer.cancel()
        for writer in list(self._writers):
            writer.close()
        if self._server is not None:
            # En Python 3.12 wait_closed espera a que no quede ninguna conexion.
            await self._server.wait_closed()
            self._server = None
            logger.info("Ventana de emparejamiento cerrada")


async def open_pairing_window(
    identity: DeviceIdentity,
    host: str,
    port: int = PAIRING_PORT,
    network: str | None = None,
    window: float = WINDOW_SECONDS,
) -> PairingListener:
    """Abre la ventana en host:port (port 0 elige uno libre) solo para la subred network.

    Sin network, la subred se lee de la interfaz que tiene la IP host. Si el
    puerto esta ocupado sube OSError (EADDRINUSE): no se busca otro,
    para que la regla del cortafuegos siga cubriendo los puertos exactos.
    """
    from services.service_probe import local_network

    check_listen_host(host)
    network = network or local_network(host)
    if not is_allowed_origin(host, network):
        raise ValueError("La IP de escucha no pertenece a la red permitida")
    listener = PairingListener(
        PairingSession(window=window), own_record(identity), identity.data_dir, network
    )
    await listener._start(host, port)
    return listener


async def join_pairing(
    identity: DeviceIdentity,
    code: str,
    host: str,
    port: int = PAIRING_PORT,
    timeout: float = STEP_TIMEOUT,
) -> PeerRecord:
    """Escribe el codigo del otro equipo; si coincide, lo guarda en paired.json."""
    normalize_code(code)  # un codigo mal escrito falla antes de gastar un intento
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    try:
        peer = await pair_as_joiner(
            code, StreamChannel(reader, writer, timeout), own_record(identity)
        )
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()
    add_paired(identity.data_dir, peer)
    return peer
