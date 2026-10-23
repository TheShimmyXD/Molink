"""Servidor SSH propio de Molink sobre asyncssh.

Solo acepta llaves publicas emparejadas y solo desde la red local: un origen
de fuera se corta antes de autenticar. Sin contrasena, sin teclado
interactivo, sin reenvio de agente, de X11 ni de puertos y sin PTY. Corre los
comandos como el usuario que abrio la app y vive solo mientras alguien lo
tiene abierto: quien llama a start_server debe llamar a close(), que corta
tambien las sesiones abiertas.

Como programa de ensayo escucha en una IP concreta hasta Ctrl+C:
    .venv/bin/python services/service_ssh_server.py --host IP --data DIR [--allow cliente.pub]
Sin --allow acepta las llaves de paired.json de DIR; sin --network, la subred
de la interfaz que tiene esa IP.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import ipaddress
import logging
import signal
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import asyncssh

if TYPE_CHECKING:
    from services.service_chat import MessageCallback
    from services.service_identity import DeviceIdentity
    from services.service_transfer import IncomingCallback

logger = logging.getLogger(__name__)

# Clave en get_extra_info de la conexion: la llave publica que el servidor acepto.
PEER_KEY_INFO = "molink_peer_key"

READ_CHUNK = 4096
DEFAULT_PORT = 47820
# Una conexion muerta (se corto la red) se da por cerrada tras KEEPALIVE_S * KEEPALIVE_MISSES
# sin respuesta, en vez de quedar colgada los minutos que tarda TCP.
KEEPALIVE_S = 5
KEEPALIVE_MISSES = 3

KeysProvider = Callable[[], Iterable[asyncssh.SSHKey]]


def check_listen_host(host: str) -> str:
    """Acepta solo una IP concreta: nunca todas las interfaces (0.0.0.0 o ::)."""
    if ipaddress.ip_address(host).is_unspecified:
        raise ValueError("Molink no escucha en todas las interfaces: usa la IP de la red local")
    return host


def is_allowed_origin(address: str, network: str) -> bool:
    """True si la IP de origen cae en la subred permitida (IPv4 mapeada incluida)."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip in ipaddress.ip_network(network, strict=False)


class _MolinkServer(asyncssh.SSHServer):
    """Una conexion entrante: filtra el origen y autentica solo con llaves emparejadas."""

    def __init__(
        self,
        allowed_keys: KeysProvider,
        network: str,
        connections: set[asyncssh.SSHServerConnection],
    ):
        self._allowed_keys = allowed_keys
        self._network = network
        self._connections = connections
        self._conn: asyncssh.SSHServerConnection | None = None
        self._origin_ok = False

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        origin = conn.get_extra_info("peername")[0]
        self._origin_ok = is_allowed_origin(origin, self._network)
        if not self._origin_ok:
            logger.warning("Conexion rechazada: origen %s fuera de %s", origin, self._network)
            conn.disconnect(
                asyncssh.DISC_HOST_NOT_ALLOWED_TO_CONNECT, "Molink solo acepta la red local"
            )
            return
        self._conn = conn
        self._connections.add(conn)
        logger.info("Conexion entrante desde %s", origin)

    def connection_lost(self, exc: Exception | None) -> None:
        self._connections.discard(self._conn)

    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return False

    def kbdint_auth_supported(self) -> bool:
        return False

    def public_key_auth_supported(self) -> bool:
        return self._origin_ok

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        # Se relee la lista en cada intento: quitar un emparejamiento corta al momento.
        allowed = {k.public_data for k in self._allowed_keys()}
        accepted = self._origin_ok and key.public_data in allowed
        if not accepted:
            logger.warning("Llave no emparejada rechazada")
        elif self._conn is not None:
            # Archivos y chat la leen para decir de que equipo viene algo.
            self._conn.set_extra_info(**{PEER_KEY_INFO: key.public_data})
        return accepted


async def _pump(reader: asyncio.StreamReader, writer) -> None:
    """Pasa la salida del comando al canal; si el canal ya se cerro, solo la drena."""
    while chunk := await reader.read(READ_CHUNK):
        with contextlib.suppress(OSError, asyncssh.Error):
            writer.write(chunk)


def exit_code(returncode: int) -> int:
    """Codigo de salida como lo da un shell: muerto por la senal N -> 128 + N."""
    return 128 - returncode if returncode < 0 else returncode


async def _feed(reader, writer: asyncio.StreamWriter) -> None:
    """Pasa al comando lo que el otro equipo manda por stdin y la cierra en su EOF.

    Lo que llega aqui (la contrasena de sudo) no se guarda ni va al log.
    """
    with contextlib.suppress(OSError, asyncssh.Error):
        while chunk := await reader.read(READ_CHUNK):
            writer.write(chunk)
            await writer.drain()
    with contextlib.suppress(OSError):
        writer.close()


async def _run_child(child: asyncio.subprocess.Process, process) -> int:
    await asyncio.gather(_pump(child.stdout, process.stdout), _pump(child.stderr, process.stderr))
    return await child.wait()


async def _run_process(process: asyncssh.SSHServerProcess) -> None:
    """Corre el comando pedido sin PTY y devuelve su salida en vivo.

    stdin del comando es la del canal: recibe lo que el otro equipo mande y
    fin de entrada cuando el otro la cierra. Si el canal se cierra antes (el
    otro equipo cancela, se cae la red o se cierra la app) se termina el grupo
    de procesos del comando: no quedan huerfanos, tampoco los que el comando
    dejo en segundo plano.
    """
    if not process.command:
        process.stderr.write(b"Molink no abre una consola interactiva.\n")
        process.exit(1)
        return
    from services.service_process import spawn, terminate

    child = await spawn(process.command)
    feeding = asyncio.ensure_future(_feed(process.stdin, child.stdin))
    finished = asyncio.ensure_future(_run_child(child, process))
    closed = asyncio.ensure_future(process.wait_closed())
    try:
        await asyncio.wait({finished, closed}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        closed.cancel()
        feeding.cancel()
        if not finished.done():
            await terminate(child)
            logger.info("Comando remoto cancelado")
            await asyncio.gather(finished, return_exceptions=True)
    if finished.cancelled() or finished.exception() is not None or process.is_closing():
        return
    returncode = finished.result()
    logger.info("Comando remoto terminado con codigo %s", returncode)
    process.exit(exit_code(returncode))


async def _handle_process(
    process: asyncssh.SSHServerProcess, on_message: MessageCallback | None
) -> None:
    """El subsistema de chat si la app lo escucha; lo demas, como un comando."""
    from services.service_chat import CHAT_SUBSYSTEM, serve_chat

    if process.subsystem == CHAT_SUBSYSTEM and on_message is not None:
        await serve_chat(process, on_message)
        return
    await _run_process(process)


@dataclass
class SshServerHandle:
    """Servidor en marcha, el puerto en el que quedo y sus conexiones vivas."""

    acceptor: asyncssh.SSHAcceptor
    host: str
    port: int
    connections: set[asyncssh.SSHServerConnection] = field(default_factory=set)

    async def close(self) -> None:
        """Deja de escuchar y corta las sesiones abiertas; el puerto queda libre."""
        self.acceptor.close()
        # asyncio.Server.wait_closed espera a que no quede ninguna conexion.
        open_conns = list(self.connections)
        for conn in open_conns:
            conn.close()
        await asyncio.gather(*(conn.wait_closed() for conn in open_conns))
        self.connections.clear()
        await self.acceptor.wait_closed()
        logger.info("Servidor cerrado en el puerto %s", self.port)


async def start_server(
    host: str,
    port: int,
    host_key: asyncssh.SSHKey,
    allowed_keys: KeysProvider,
    network: str,
    inbox: Path | None = None,
    on_incoming: IncomingCallback | None = None,
    on_message: MessageCallback | None = None,
) -> SshServerHandle:
    """Abre el servidor en host:port (port 0 elige uno libre) solo para la subred network.

    Con inbox acepta archivos por SFTP en esa carpeta (service_transfer) y
    avisa de cada uno a on_incoming; sin inbox no hay SFTP. Con on_message
    recibe mensajes de chat (service_chat); sin el, no hay chat.
    """
    check_listen_host(host)
    if not is_allowed_origin(host, network):
        raise ValueError("La IP de escucha no pertenece a la red permitida")
    connections: set[asyncssh.SSHServerConnection] = set()
    sftp_factory = None
    if inbox is not None:
        from services.service_transfer import inbox_sftp_factory

        sftp_factory = inbox_sftp_factory(inbox, on_incoming)
    acceptor = await asyncssh.create_server(
        lambda: _MolinkServer(allowed_keys, network, connections),
        host,
        port,
        server_host_keys=[host_key],
        process_factory=functools.partial(_handle_process, on_message=on_message),
        sftp_factory=sftp_factory,
        encoding=None,
        allow_pty=False,
        agent_forwarding=False,
        x11_forwarding=False,
        config=None,
        keepalive_interval=KEEPALIVE_S,
        keepalive_count_max=KEEPALIVE_MISSES,
    )
    handle = SshServerHandle(acceptor, host, acceptor.get_port(), connections)
    logger.info("Servidor escuchando en el puerto %s", handle.port)
    return handle


async def start_molink_server(
    identity: DeviceIdentity,
    host: str,
    port: int = DEFAULT_PORT,
    network: str | None = None,
    inbox: Path | None = None,
    on_incoming: IncomingCallback | None = None,
    on_message: MessageCallback | None = None,
) -> SshServerHandle:
    """El servidor de la app: llave de host de la identidad y llaves de paired.json.

    Sin network, la subred se lee de la interfaz que tiene la IP host; con
    inbox, los archivos que lleguen van a esa carpeta.
    """
    from services.service_paired import authorized_user_keys
    from services.service_probe import local_network

    network = network or local_network(host)
    return await start_server(
        host,
        port,
        identity.host_key,
        lambda: authorized_user_keys(identity.data_dir),
        network,
        inbox,
        on_incoming,
        on_message,
    )


async def _serve_until_stopped(args: argparse.Namespace) -> None:
    # Solo el modo de ensayo lee la llave del disco; start_server la recibe hecha.
    from services.service_identity import HOST_KEY_NAME, load_or_create_key
    from services.service_paired import authorized_user_keys
    from services.service_probe import local_network

    host = check_listen_host(args.host)
    network = args.network or local_network(host)
    host_key = load_or_create_key(args.data / HOST_KEY_NAME)
    if args.allow:
        fixed = [asyncssh.read_public_key(str(path)) for path in args.allow]
        allowed: KeysProvider = lambda: fixed  # noqa: E731
    else:
        allowed = lambda: authorized_user_keys(args.data)  # noqa: E731
    handle = await start_server(host, args.port, host_key, allowed, network)
    lines = [
        f"Escuchando en {handle.host}:{handle.port} solo para {network}",
        f"Huella del equipo: {host_key.get_fingerprint()}",
    ]
    lines += [f"Llave permitida: {key.get_fingerprint()}" for key in allowed()]
    sys.stdout.write("\n".join(lines) + "\nCtrl+C para cerrar.\n")
    sys.stdout.flush()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        # Windows no tiene manejadores de senal en asyncio: alli Ctrl+C cancela la tarea.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop.set)
    try:
        await stop.wait()
    finally:
        await handle.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Servidor SSH de Molink para ensayos a mano.")
    parser.add_argument("--host", required=True, help="IP de la red local en la que escuchar")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--network", help="subred permitida (por defecto la de la interfaz)")
    parser.add_argument("--data", type=Path, required=True, help="carpeta de datos de Molink")
    parser.add_argument(
        "--allow", type=Path, nargs="+", help="llaves publicas permitidas (por defecto paired.json)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # asyncssh escribe en INFO el comando remoto: eso es contenido del canal.
    logging.getLogger("asyncssh").setLevel(logging.WARNING)
    asyncio.run(_serve_until_stopped(args))


if __name__ == "__main__":
    # Como script, la raiz del proyecto no esta en sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
