"""Descubrimiento de Molink en la red local con zeroconf (mDNS).

Cada app anuncia _molink._tcp.local. con su IP de la red local y el puerto del
servidor; la otra lo busca. Solo IPv4 y solo en la interfaz indicada: nunca en
todas. El anuncio no lleva llaves ni codigos, solo nombre, IP, puerto, version y
sistema (os=linux u os=windows; sin ella, Linux).

Como programa de ensayo:
    .venv/bin/python services/service_discovery.py announce --host IP --name N
    .venv/bin/python services/service_discovery.py browse --host IP
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ipaddress
import logging
import signal
import socket
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_molink._tcp.local."
PROTOCOL_VERSION = "1"
DEFAULT_PORT = 47820
INFO_TIMEOUT_MS = 1500


@dataclass(frozen=True)
class Peer:
    """Otro equipo con Molink abierto, tal como se anuncia."""

    name: str
    address: str
    port: int
    os: str = "linux"  # OS_LINUX de logic/_00_logic_platform.py


def instance_name(service_name: str) -> str:
    """'equipo._molink._tcp.local.' -> 'equipo'."""
    return service_name.removesuffix("." + SERVICE_TYPE)


def peer_from_info(
    service_name: str,
    addresses: Iterable[str],
    port: int | None,
    own_name: str,
    subnet: ipaddress.IPv4Network | None,
    properties: dict | None = None,
) -> Peer | None:
    """Convierte un anuncio en Peer; None si es el propio equipo o esta fuera de la subred."""
    # Dentro de la funcion: como programa de ensayo la raiz aun no esta en sys.path.
    from logic._00_logic_platform import OS_KEY, peer_os

    name = instance_name(service_name)
    if name == own_name or not port:
        return None
    for address in addresses:
        if subnet is None or ipaddress.ip_address(address) in subnet:
            return Peer(name, address, port, peer_os((properties or {}).get(OS_KEY.encode())))
    return None


def _check_host(host: str) -> str:
    if ipaddress.ip_address(host).is_unspecified:
        raise ValueError("Molink no se anuncia en todas las interfaces: usa la IP de la red local")
    return host


class Announcer:
    """Anuncia este equipo hasta que se llama a close()."""

    def __init__(self, name: str, host: str, port: int):
        from logic._00_logic_platform import OS_KEY, local_os

        self._host = _check_host(host)
        self._info = AsyncServiceInfo(
            SERVICE_TYPE,
            f"{name}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(host)],
            port=port,
            properties={"v": PROTOCOL_VERSION, OS_KEY: local_os()},
            server=f"{name}.local.",
        )
        self._zeroconf: AsyncZeroconf | None = None

    async def start(self) -> None:
        self._zeroconf = AsyncZeroconf(interfaces=[self._host], ip_version=IPVersion.V4Only)
        await self._zeroconf.async_register_service(self._info)
        logger.info("Anuncio de Molink publicado en el puerto %s", self._info.port)

    async def close(self) -> None:
        if self._zeroconf is None:
            return
        await self._zeroconf.async_unregister_service(self._info)
        await self._zeroconf.async_close()
        self._zeroconf = None
        logger.info("Anuncio de Molink retirado")


async def browse(
    host: str,
    own_name: str,
    timeout: float,
    subnet: ipaddress.IPv4Network | None = None,
) -> tuple[list[Peer], float | None]:
    """Busca durante timeout segundos; devuelve los equipos y cuando aparecio el primero."""
    zeroconf = AsyncZeroconf(interfaces=[_check_host(host)], ip_version=IPVersion.V4Only)
    names: set[str] = set()
    started = time.monotonic()
    first_seen: list[float] = []

    def on_change(zeroconf, service_type, name, state_change) -> None:
        if state_change is ServiceStateChange.Added and instance_name(name) != own_name:
            names.add(name)
            if not first_seen:
                first_seen.append(time.monotonic() - started)

    browser = AsyncServiceBrowser(zeroconf.zeroconf, SERVICE_TYPE, handlers=[on_change])
    try:
        await asyncio.sleep(timeout)
        peers = []
        for name in sorted(names):
            info = AsyncServiceInfo(SERVICE_TYPE, name)
            if not await info.async_request(zeroconf.zeroconf, INFO_TIMEOUT_MS):
                continue
            peer = peer_from_info(
                name, info.parsed_addresses(), info.port, own_name, subnet, info.properties
            )
            if peer is not None:
                peers.append(peer)
    finally:
        await browser.async_cancel()
        await zeroconf.async_close()
    logger.info("Busqueda terminada: %s equipos", len(peers))
    return peers, (first_seen[0] if first_seen else None)


async def _announce_until_stopped(args: argparse.Namespace) -> None:
    announcer = Announcer(args.name, args.host, args.port)
    await announcer.start()
    sys.stdout.write(f"Anunciando {args.name} en {args.host}:{args.port}. Ctrl+C para cerrar.\n")
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
        await announcer.close()


async def _browse_once(args: argparse.Namespace) -> int:
    subnet = ipaddress.ip_network(args.subnet) if args.subnet else None
    peers, first = await browse(args.host, args.name, args.timeout, subnet)
    first_text = f"{first:.2f} s" if first is not None else "nunca"
    sys.stdout.write(f"Equipos encontrados: {len(peers)} (primero a los {first_text})\n")
    for peer in peers:
        sys.stdout.write(f"  {peer.name} {peer.address}:{peer.port}\n")
    return 0 if peers else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Descubrimiento de Molink para ensayos a mano.")
    parser.add_argument("mode", choices=["announce", "browse"])
    parser.add_argument("--host", required=True, help="IP de la red local")
    parser.add_argument("--name", default=socket.gethostname(), help="nombre de este equipo")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=3.0, help="segundos de busqueda")
    parser.add_argument("--subnet", help="solo equipos de esta subred, p. ej. 192.0.2.0/24")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.mode == "announce":
        asyncio.run(_announce_until_stopped(args))
        return 0
    return asyncio.run(_browse_once(args))


if __name__ == "__main__":
    # Como script, la raiz del proyecto no esta en sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
