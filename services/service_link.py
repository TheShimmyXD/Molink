"""Responsabilidad unica: la presencia de este equipo en la red mientras la app esta abierta.

Junta las piezas de emparejamiento y servidor como lo hace la orden de consola (service_console.serve),
pero para la interfaz: servidor SSH solo para emparejados (47820), anuncio
zeroconf, busqueda de los otros equipos, ventana del codigo (47821) y escribir
el codigo de otro. Lo que se hace con un equipo emparejado (comandos, archivos,
chat) esta en service_link_peer. Todo es asyncio y corre en el bucle de
core/async_loop.py. La ventana principal crea
una sola sesion y la comparten las pantallas; se puede cerrar y
volver a abrir en otra IP.
Los errores esperables vuelven como LinkError con un texto para el usuario y
que hacer; nada de lo que pasa por aqui va a un log salvo el puerto y el nombre.
"""

from __future__ import annotations

import errno
import ipaddress
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from services.service_discovery import Peer
from services.service_link_peer import LinkError, PeerActions
from services.service_pairing_listener import PAIRING_PORT
from services.service_ssh_server import DEFAULT_PORT

if TYPE_CHECKING:
    from services.service_chat import ChatMessage, MessageCallback
    from services.service_identity import DeviceIdentity
    from services.service_paired import PeerRecord
    from services.service_pairing_listener import PairingListener
    from services.service_ssh_server import SshServerHandle
    from services.service_transfer import IncomingCallback, IncomingEvent

logger = logging.getLogger(__name__)

BROWSE_S = 3.0
JOIN_TIMEOUT_S = 10.0
# Un equipo visto sigue en la red este tiempo aunque una busqueda no lo vea:
# por wifi el mDNS se pierde a ratos y el equipo no debe parpadear.
SEEN_GRACE_S = 15.0

Browse = Callable[[str, str, float, ipaddress.IPv4Network], Awaitable[tuple[list[Peer], object]]]


def _port_error(exc: OSError, port: int) -> LinkError:
    if exc.errno == errno.EADDRINUSE:
        return LinkError(
            f"El puerto {port} ya está ocupado.",
            "¿Hay otro Molink abierto en este equipo? Ciérralo y reintenta.",
        )
    return LinkError(f"No se pudo abrir el puerto {port}.", str(exc.strerror or exc))


@dataclass
class WindowInfo:
    """Ventana del codigo recien abierta: lo que la UI necesita mostrar."""

    code: str
    port: int
    seconds: float


@dataclass
class LinkSettings:
    host: str
    ssh_port: int = DEFAULT_PORT
    pair_port: int = PAIRING_PORT
    network: str | None = None  # sin network, la de la interfaz de host
    announce: bool = True  # las pruebas en 127.0.0.1 no anuncian (mDNS no va por loopback)
    inbox: Path | None = None  # carpeta de llegada; sin ella no se reciben archivos


@dataclass
class LinkSession(PeerActions):
    """Servidor y anuncio abiertos; ventana y busquedas bajo demanda."""

    identity: DeviceIdentity
    settings: LinkSettings
    browse_fn: Browse | None = None
    clock: Callable[[], float] = time.monotonic
    # Archivos que llegan, con peer puesto; se llama en el hilo del bucle.
    on_incoming: IncomingCallback | None = None
    # Mensajes de chat que llegan, con peer puesto; sin el no se acusan.
    on_message: MessageCallback | None = None
    _server: SshServerHandle | None = None
    _announcer: object | None = None
    _listener: PairingListener | None = None
    _network: str = ""
    _seen: dict[str, Peer] = field(default_factory=dict)  # vistos hace poco, por nombre
    _last_seen: dict[str, float] = field(default_factory=dict)
    _closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)
    _incoming_peer: dict[int, str] = field(default_factory=dict)  # por transfer_id
    _chats: dict = field(default_factory=dict)
    _chat_locks: dict = field(default_factory=dict)

    @property
    def host(self) -> str:
        return self.settings.host

    @property
    def ssh_port(self) -> int:
        return self._server.port if self._server is not None else 0

    async def start(self, host: str | None = None) -> None:
        """Abre el servidor y el anuncio (en host si se da); LinkError si no se puede."""
        from services.service_probe import local_network
        from services.service_ssh_server import start_molink_server

        if host is not None:
            self.settings.host = host
        host = self.settings.host
        if not host:
            raise LinkError(
                "Este equipo no está conectado a ninguna red.",
                "Conéctalo a la wifi o al cable y reintenta.",
            )
        try:
            self._network = self.settings.network or local_network(host)
        except ValueError as exc:
            raise LinkError(f"La IP {host} ya no es de este equipo.", "Reintenta.") from exc
        try:
            self._server = await start_molink_server(
                self.identity,
                host,
                self.settings.ssh_port,
                self._network,
                self.settings.inbox,
                self._incoming,
                self._message,
            )
        except OSError as exc:
            raise _port_error(exc, self.settings.ssh_port) from exc
        self._closers.append(self._server.close)
        if self.settings.announce:
            from services.service_discovery import Announcer

            announcer = Announcer(self.identity.name, host, self._server.port)
            await announcer.start()
            self._announcer = announcer
            self._closers.append(announcer.close)

    async def browse(self, seconds: float = BROWSE_S) -> list[Peer]:
        """Equipos con Molink abierto en la subred, sin este, vistos en los ultimos SEEN_GRACE_S."""
        if self.browse_fn is None:
            from services.service_discovery import browse as browse_fn
        else:
            browse_fn = self.browse_fn
        subnet = ipaddress.ip_network(self._network, strict=False)
        peers, _ = await browse_fn(self.host, self.identity.name, seconds, subnet)
        now = self.clock()
        for peer in peers:
            self._seen[peer.name] = peer
            self._last_seen[peer.name] = now
        for name, seen_at in list(self._last_seen.items()):
            if now - seen_at > SEEN_GRACE_S:
                del self._last_seen[name]
                self._seen.pop(name, None)
        return list(self._seen.values())

    async def reachable(self) -> list[Peer]:
        """Equipos emparejados vistos en la red hace poco (SEEN_GRACE_S)."""
        return [self._seen[name] for name in self.paired_names() if name in self._seen]

    async def open_window(self) -> WindowInfo:
        """Abre la ventana del codigo; si ya habia una, la cierra antes."""
        from services.service_pairing_listener import open_pairing_window

        await self.close_window()
        try:
            listener = await open_pairing_window(
                self.identity, self.host, self.settings.pair_port, self._network
            )
        except OSError as exc:
            raise _port_error(exc, self.settings.pair_port) from exc
        self._listener = listener
        return WindowInfo(listener.session.code, listener.port, listener.remaining())

    async def wait_window(self) -> tuple[PeerRecord | None, str]:
        """Espera a que la ventana termine: (equipo emparejado o None, por que termino).

        El por que es PAIRED, EXPIRED, LOCKED o CLOSED (cerrada por el usuario).
        """
        listener = self._listener
        if listener is None:
            return None, "CLOSED"
        try:
            peer = await listener.wait()
            return peer, listener.session.state().value
        finally:
            if self._listener is listener:
                self._listener = None

    async def close_window(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            await listener.close()

    async def join(self, code: str, address: str, port: int | None = None) -> PeerRecord:
        """Escribe el codigo que muestra el otro equipo en su ventana."""
        from services.service_pairing import PairingError
        from services.service_pairing_listener import join_pairing

        port = port or self.settings.pair_port
        try:
            return await join_pairing(self.identity, code, address, port, JOIN_TIMEOUT_S)
        except ValueError as exc:
            raise LinkError("El código tiene 6 dígitos.", "Escríbelo como aparece allá.") from exc
        except PairingError as exc:
            raise LinkError(
                "El código no coincide o la ventana ya se cerró.",
                "Revisa el código; si se acabó el tiempo, pide uno nuevo allá.",
            ) from exc
        except (OSError, TimeoutError) as exc:
            raise LinkError(
                f"No se pudo llegar a {address}:{port}.",
                "Allá pulsa 'Mostrar mi código'; si ya está, revisa el cortafuegos.",
            ) from exc

    async def close(self) -> None:
        """Cierra ventana, anuncio y servidor: no queda ningun puerto abierto."""
        await self.close_window()
        await self._close_chats()
        while self._closers:
            closer = self._closers.pop()
            try:
                await closer()
            except Exception:  # noqa: BLE001 (se cierra todo aunque falle una pieza)
                logger.exception("Fallo al cerrar una pieza del enlace")
        self._server = None
        self._announcer = None
        self._seen = {}
        self._last_seen = {}

    def _incoming(self, event: IncomingEvent) -> None:
        """Pone el nombre del equipo que envia y pasa el aviso a on_incoming."""
        import dataclasses

        from services.service_transfer import IncomingKind

        if self.on_incoming is None:
            return
        peer = self._incoming_peer.get(event.transfer_id)
        if peer is None:
            peer = self._peer_by_key(event.peer_key)
            self._incoming_peer[event.transfer_id] = peer
        if event.kind in (IncomingKind.DONE, IncomingKind.CUT):
            self._incoming_peer.pop(event.transfer_id, None)
        self.on_incoming(dataclasses.replace(event, peer=peer))

    def _message(self, message: ChatMessage) -> None:
        """Pone el nombre del equipo que escribe; sin on_message no hay acuse."""
        import dataclasses

        if self.on_message is None:
            raise RuntimeError("La app no escucha el chat")
        self.on_message(dataclasses.replace(message, peer=self._peer_by_key(message.peer_key)))
