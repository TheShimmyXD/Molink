"""Orden de consola de Molink: el primer contacto sin interfaz.

    .venv/bin/python services/service_console.py serve --host IP [--pair]
    .venv/bin/python services/service_console.py pair --to IP
    .venv/bin/python services/service_console.py run EQUIPO --host IP -- CMD...
    .venv/bin/python services/service_console.py peers

serve abre el servidor y el anuncio hasta Ctrl+C; con --pair abre ademas la
ventana de 2 minutos y escribe el codigo en esta terminal (nunca en un log).
pair pide el codigo que muestra el otro equipo. run busca al equipo con
zeroconf (o va directo con --to IP[:PUERTO]) y pasa la salida en vivo; sale
con el codigo del comando remoto. Todas aceptan --data DIR (por defecto
~/.local/share/molink). La interfaz de F3 reemplaza esta orden con las mismas
piezas.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import errno
import ipaddress
import logging
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

import asyncssh

if TYPE_CHECKING:
    from services.service_identity import DeviceIdentity
    from services.service_paired import PeerRecord

logger = logging.getLogger(__name__)

BROWSE_S = 3.0
CONNECT_TIMEOUT_S = 10.0
EXIT_USAGE = 2
EXIT_NO_STATUS = 255
EXIT_INTERRUPTED = 130

Show = Callable[[str], None]


class ConsoleError(Exception):
    """Un problema que se le explica al usuario en una linea."""


def format_code(code: str) -> str:
    """'123456' -> '123 456', como se dicta."""
    return f"{code[:3]} {code[3:]}"


def parse_target(text: str, default_port: int) -> tuple[str, int]:
    """'IP' o 'IP:PUERTO' -> (IP, puerto)."""
    address, _, port = text.partition(":")
    try:
        ipaddress.ip_address(address)
        return address, int(port) if port else default_port
    except ValueError as exc:
        raise ConsoleError(f"Direccion no valida: {text} (se espera IP o IP:PUERTO)") from exc


def _busy(exc: OSError, port: int) -> ConsoleError:
    if exc.errno == errno.EADDRINUSE:
        return ConsoleError(
            f"El puerto {port} ya esta ocupado: hay otro Molink abierto? Cierralo o usa otro puerto."
        )
    return ConsoleError(f"No se pudo abrir el puerto {port}: {exc.strerror}")


def find_peer(data_dir: Path, name: str) -> PeerRecord:
    from services.service_paired import load_paired

    for peer in load_paired(data_dir):
        if peer.name == name:
            return peer
    raise ConsoleError(f"No hay ningun equipo emparejado llamado {name} (mira `peers`)")


async def locate(identity: DeviceIdentity, name: str, host: str | None) -> tuple[str, int]:
    """Busca al equipo por zeroconf en la subred de host."""
    from services.service_discovery import browse
    from services.service_probe import local_network

    if host is None:
        raise ConsoleError("Para buscar al equipo hace falta --host (o ve directo con --to)")
    subnet = ipaddress.ip_network(local_network(host), strict=False)
    peers, _ = await browse(host, identity.name, BROWSE_S, subnet)
    for peer in peers:
        if peer.name == name:
            return peer.address, peer.port
    raise ConsoleError(f"{name} no aparece en la red en {BROWSE_S:.0f} s: tiene Molink abierto?")


async def _report(listener, show: Show) -> None:
    peer = await listener.wait()
    if peer is None:
        show(f"La ventana se cerro sin emparejar ({listener.session.state()}).")
    else:
        show(f"Emparejado con {peer.name}; huella de su equipo: {peer.host_fingerprint()}")


async def serve(
    identity: DeviceIdentity,
    host: str,
    port: int,
    stop: asyncio.Event,
    show: Show,
    pair_port: int | None = None,
    network: str | None = None,
    announce: bool = True,
) -> None:
    """Servidor, anuncio y, con pair_port, ventana de emparejamiento, hasta stop."""
    from logic._00_logic_pairing import MAX_ATTEMPTS
    from services.service_discovery import Announcer
    from services.service_pairing_listener import open_pairing_window
    from services.service_ssh_server import start_molink_server

    async with contextlib.AsyncExitStack() as stack:
        try:
            handle = await start_molink_server(identity, host, port, network)
        except OSError as exc:
            raise _busy(exc, port) from exc
        stack.push_async_callback(handle.close)
        show(f"Molink de {identity.name} escuchando en {handle.host}:{handle.port}")
        show(f"Huella de este equipo: {identity.host_key.get_fingerprint()}")
        if announce:
            announcer = Announcer(identity.name, host, handle.port)
            await announcer.start()
            stack.push_async_callback(announcer.close)
        if pair_port is not None:
            try:
                listener = await open_pairing_window(identity, host, pair_port, network)
            except OSError as exc:
                raise _busy(exc, pair_port) from exc
            stack.push_async_callback(listener.close)
            show(
                f"Codigo de emparejamiento: {format_code(listener.session.code)} "
                f"(puerto {listener.port}, {listener.remaining():.0f} s, {MAX_ATTEMPTS} intentos)"
            )
            stack.callback(asyncio.create_task(_report(listener, show)).cancel)
        show("Ctrl+C para cerrar.")
        await stop.wait()


async def pair(identity: DeviceIdentity, code: str, address: str, port: int) -> PeerRecord:
    from services.service_pairing import PairingError
    from services.service_pairing_listener import join_pairing

    try:
        return await join_pairing(identity, code, address, port)
    except ValueError as exc:
        raise ConsoleError(str(exc)) from exc
    except PairingError as exc:
        raise ConsoleError(f"No se emparejo: {exc.reason.value}") from exc
    except (OSError, TimeoutError) as exc:
        raise ConsoleError(
            f"No se pudo conectar a {address}:{port}: la ventana esta abierta alla? "
            "el puerto esta abierto en ufw?"
        ) from exc


async def run_remote(
    identity: DeviceIdentity,
    name: str,
    command: str,
    target: tuple[str, int] | None,
    host: str | None,
    out: BinaryIO,
    err: BinaryIO,
) -> int:
    """Corre command en el equipo emparejado name; devuelve su codigo de salida."""
    from services.service_ssh_client import STDOUT, connect_peer, stream_command

    peer = find_peer(identity.data_dir, name)
    address, port = target or await locate(identity, name, host)
    host_key = asyncssh.import_public_key(peer.host_key)

    def write(stream: str, data: bytes) -> None:
        sink = out if stream == STDOUT else err
        sink.write(data)
        sink.flush()

    try:
        conn = await asyncio.wait_for(
            connect_peer(address, port, identity.user_key, host_key), CONNECT_TIMEOUT_S
        )
    except asyncssh.PermissionDenied as exc:
        raise ConsoleError(f"{name} no tiene emparejado a este equipo") from exc
    except asyncssh.HostKeyNotVerifiable as exc:
        raise ConsoleError(f"El equipo en {address}:{port} no es el {name} emparejado") from exc
    except asyncssh.DisconnectError as exc:
        raise ConsoleError(f"{name} corto la conexion: {exc.reason}") from exc
    except (OSError, TimeoutError) as exc:
        raise ConsoleError(
            f"No se pudo conectar a {address}:{port}: Molink esta abierto alla? "
            "el puerto esta abierto en ufw?"
        ) from exc
    async with conn:
        status = await stream_command(conn, command, write)
    return EXIT_NO_STATUS if status is None else status


def _print(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


async def _serve_until_signal(identity: DeviceIdentity, args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        # Windows no tiene manejadores de senal en asyncio: alli Ctrl+C cancela la tarea.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop.set)
    pair_port = args.pair_port if args.pair else None
    await serve(identity, args.host, args.port, stop, _print, pair_port, args.network)


def _peers(identity: DeviceIdentity) -> None:
    from services.service_paired import load_paired

    _print(f"Este equipo: {identity.name} ({identity.host_key.get_fingerprint()})")
    peers = load_paired(identity.data_dir)
    if not peers:
        _print("Sin equipos emparejados.")
    for peer in peers:
        _print(f"{peer.name}  equipo {peer.host_fingerprint()}  desde {peer.paired_at}")


def _parser() -> argparse.ArgumentParser:
    from services.service_pairing_listener import PAIRING_PORT
    from services.service_ssh_server import DEFAULT_PORT

    parser = argparse.ArgumentParser(
        description="Molink sin interfaz: emparejar y correr comandos."
    )
    parser.add_argument("--data", type=Path, help="carpeta de datos (por defecto la de Molink)")
    sub = parser.add_subparsers(dest="action", required=True)

    serve_p = sub.add_parser("serve", help="abre el servidor y el anuncio hasta Ctrl+C")
    serve_p.add_argument("--host", required=True, help="IP de este equipo en la red local")
    serve_p.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_p.add_argument("--pair", action="store_true", help="abre la ventana de emparejamiento")
    serve_p.add_argument("--pair-port", type=int, default=PAIRING_PORT)
    serve_p.add_argument("--network", help="subred permitida (por defecto la de la interfaz)")

    pair_p = sub.add_parser("pair", help="escribe el codigo que muestra el otro equipo")
    pair_p.add_argument("--to", required=True, help="IP[:PUERTO] de la ventana del otro equipo")

    run_p = sub.add_parser("run", help="corre un comando en un equipo emparejado")
    run_p.add_argument("name", help="nombre del equipo emparejado")
    run_p.add_argument("--host", help="IP de este equipo, para buscar al otro con zeroconf")
    run_p.add_argument("--to", help="IP[:PUERTO] del otro equipo, sin buscarlo")
    run_p.add_argument("command", nargs="*", help="comando (despues de --)")

    sub.add_parser("peers", help="lista los equipos emparejados")
    return parser


def main(argv: list[str] | None = None) -> int:
    from services.service_identity import load_or_create_identity
    from services.service_pairing_listener import PAIRING_PORT
    from services.service_ssh_server import DEFAULT_PORT

    argv = sys.argv[1:] if argv is None else list(argv)
    # Lo que va despues de -- es el comando remoto, tal cual (como en ssh).
    remote = argv[argv.index("--") + 1 :] if "--" in argv else []
    args = _parser().parse_args(argv[: argv.index("--")] if "--" in argv else argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # asyncssh escribe en INFO el comando remoto: eso es contenido del canal.
    logging.getLogger("asyncssh").setLevel(logging.WARNING)
    try:
        identity = load_or_create_identity(args.data)
        if args.action == "serve":
            asyncio.run(_serve_until_signal(identity, args))
        elif args.action == "pair":
            address, port = parse_target(args.to, PAIRING_PORT)
            code = input("Codigo que muestra el otro equipo: ")
            peer = asyncio.run(pair(identity, code, address, port))
            _print(f"Emparejado con {peer.name}; huella de su equipo: {peer.host_fingerprint()}")
        elif args.action == "run":
            command = " ".join(args.command + remote)
            if not command:
                raise ConsoleError("Falta el comando: run EQUIPO --host IP -- CMD")
            target = parse_target(args.to, DEFAULT_PORT) if args.to else None
            return asyncio.run(
                run_remote(
                    identity,
                    args.name,
                    command,
                    target,
                    args.host,
                    sys.stdout.buffer,
                    sys.stderr.buffer,
                )
            )
        else:
            _peers(identity)
    except (ConsoleError, ValueError) as exc:
        # ValueError: una IP que no es de este equipo o un nombre mal escrito.
        sys.stderr.write(f"{exc}\n")
        return EXIT_USAGE
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    return 0


if __name__ == "__main__":
    # Como script, la raiz del proyecto no esta en sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
