"""Sondeo de solo lectura del equipo.

Reune lo que Molink necesita saber de un equipo antes de abrir el canal:
Python, sesion grafica, herramienta de portapapeles, IP y subred, ufw,
usuario y puertos que ya escuchan (sshd del sistema, mDNS).

Nada aqui modifica el sistema: no usa sudo, systemctl ni ufw; ufw se
consulta leyendo /etc/ufw/ufw.conf. Solo usa la biblioteca estandar para
poder copiarse y correrse en otro equipo sin instalar nada:

    python3 services/service_probe.py
"""

from __future__ import annotations

import getpass
import ipaddress
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

UFW_CONF = Path("/etc/ufw/ufw.conf")
SSH_PORT = 22
MDNS_PORT = 5353
COMMAND_TIMEOUT_S = 5

# Herramienta de portapapeles por sesion y el paquete que la instala.
CLIPBOARD_TOOLS = {
    "x11": (("xclip",), "xclip"),
    "wayland": (("wl-copy", "wl-paste"), "wl-clipboard"),
}


@dataclass
class NetInterface:
    name: str
    address: str
    network: str


@dataclass
class ProbeResult:
    hostname: str
    user: str
    python: str
    session_type: str
    desktop: str
    clipboard_tool: str
    clipboard_package: str
    interfaces: list[NetInterface] = field(default_factory=list)
    default_iface: str = ""
    ufw: str = "no instalado"
    sshd_listening: bool = False
    mdns_listening: bool = False


# -- Analisis puro (probado en tests/test_service_probe.py) ----------------


def parse_ip_addr(output: str) -> list[NetInterface]:
    """Lee `ip -4 -o addr show scope global` y devuelve las interfaces."""
    interfaces = []
    for line in output.splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue
        name = parts[1]
        iface = ipaddress.ip_interface(parts[parts.index("inet") + 1])
        interfaces.append(NetInterface(name, str(iface.ip), str(iface.network)))
    return interfaces


def network_of(host: str, interfaces: list[NetInterface]) -> str:
    """Subred de la interfaz que tiene la IP host; ValueError si ninguna la tiene."""
    for iface in interfaces:
        if iface.address == host:
            return iface.network
    raise ValueError("Esa IP no es de ninguna interfaz de este equipo")


def parse_default_iface(output: str) -> str:
    """Lee `ip route show default` y devuelve la interfaz de la ruta por defecto."""
    for line in output.splitlines():
        parts = line.split()
        if parts[:1] == ["default"] and "dev" in parts:
            return parts[parts.index("dev") + 1]
    return ""


def default_address(interfaces: list[NetInterface], default_iface: str) -> str:
    """IP de la interfaz de la ruta por defecto; '' si no hay red."""
    for iface in interfaces:
        if iface.name == default_iface:
            return iface.address
    return ""


def parse_ufw_conf(text: str | None) -> str:
    """Estado de ufw a partir del texto de ufw.conf (None si no existe)."""
    if text is None:
        return "no instalado"
    for line in text.splitlines():
        key, _, value = line.strip().partition("=")
        if key == "ENABLED":
            return "activo" if value.strip().lower() == "yes" else "inactivo"
    return "desconocido"


def parse_listening_ports(output: str) -> set[int]:
    """Puertos locales en `ss -H -tln` o `ss -H -uln` (cuarta columna)."""
    ports = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        port = parts[3].rpartition(":")[2]
        if port.isdigit():
            ports.add(int(port))
    return ports


def detect_session(env: dict[str, str]) -> tuple[str, str]:
    """Tipo de sesion (x11, wayland, tty) y escritorio desde el entorno."""
    session = env.get("XDG_SESSION_TYPE", "").lower()
    if session not in ("x11", "wayland"):
        if env.get("WAYLAND_DISPLAY"):
            session = "wayland"
        elif env.get("DISPLAY"):
            session = "x11"
        else:
            session = session or "tty"
    return session, env.get("XDG_CURRENT_DESKTOP", "")


def detect_clipboard(session: str, which=shutil.which) -> tuple[str, str]:
    """Herramienta de portapapeles disponible y el paquete que la provee."""
    tools, package = CLIPBOARD_TOOLS.get(session, ((), ""))
    if not tools:
        return "sin sesion grafica", ""
    missing = [tool for tool in tools if which(tool) is None]
    if missing:
        return "falta " + ", ".join(missing), package
    return " + ".join(tools), package


# -- Lectura del sistema ---------------------------------------------------


def _run(args: list[str]) -> str:
    """Corre una orden de solo lectura; devuelve stdout o "" si falla."""
    try:
        done = subprocess.run(
            args, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _ip_addr_output() -> str:
    return _run(["ip", "-4", "-o", "addr", "show", "scope", "global"])


def local_network(host: str) -> str:
    """Subred de la red local a la que pertenece la IP host, leida con `ip`."""
    return network_of(host, parse_ip_addr(_ip_addr_output()))


def default_host() -> str:
    """IP de este equipo en la red local (la de la ruta por defecto); '' sin red."""
    return default_address(
        parse_ip_addr(_ip_addr_output()),
        parse_default_iface(_run(["ip", "route", "show", "default"])),
    )


def probe() -> ProbeResult:
    """Sondea el equipo actual sin modificar nada."""
    session, desktop = detect_session(dict(os.environ))
    tool, package = detect_clipboard(session)
    tcp_ports = parse_listening_ports(_run(["ss", "-H", "-tln"]))
    udp_ports = parse_listening_ports(_run(["ss", "-H", "-uln"]))
    return ProbeResult(
        hostname=socket.gethostname(),
        user=getpass.getuser(),
        python=platform.python_version(),
        session_type=session,
        desktop=desktop,
        clipboard_tool=tool,
        clipboard_package=package,
        interfaces=parse_ip_addr(_ip_addr_output()),
        default_iface=parse_default_iface(_run(["ip", "route", "show", "default"])),
        ufw=parse_ufw_conf(_read_text(UFW_CONF)),
        sshd_listening=SSH_PORT in tcp_ports,
        mdns_listening=MDNS_PORT in udp_ports,
    )


def format_report(result: ProbeResult) -> str:
    """Tabla en Markdown lista para pegar en PRUEBAS.md."""
    session = result.session_type + (f" ({result.desktop})" if result.desktop else "")
    clipboard = result.clipboard_tool
    if result.clipboard_tool.startswith("falta"):
        clipboard += f" (paquete {result.clipboard_package})"
    nets = [
        f"{i.name} {i.address} ({i.network})" + (" *" if i.name == result.default_iface else "")
        for i in result.interfaces
    ]
    rows = [
        ("Equipo", result.hostname),
        ("Usuario", result.user),
        ("Python", result.python),
        ("Sesion grafica", session),
        ("Portapapeles", clipboard),
        ("Red (* ruta por defecto)", "; ".join(nets) or "sin IPv4 global"),
        ("ufw", result.ufw),
        ("sshd del sistema (puerto 22)", "escuchando" if result.sshd_listening else "no escucha"),
        ("mDNS (puerto 5353)", "escuchando" if result.mdns_listening else "no escucha"),
    ]
    lines = ["| Dato | Valor |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(format_report(probe()))
