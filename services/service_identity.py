"""Identidad del equipo: carpeta de datos, llaves ed25519 y nombre.

Todo vive en ~/.local/share/molink/ (o $XDG_DATA_HOME/molink): carpeta 700 y
archivos 600 desde que se crean. Nada se escribe en ~/.ssh: la carpeta
se rechaza si cae dentro de ella.

- user_key: con ella este equipo entra al servidor del otro.
- host_key: con ella el servidor de este equipo se presenta.
- identity.json: el nombre con que se anuncia en la red local.

Cada llave deja al lado su .pub para sacar la huella con ssh-keygen -lf.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path

import asyncssh

logger = logging.getLogger(__name__)

USER_KEY_NAME = "user_key"
HOST_KEY_NAME = "host_key"
IDENTITY_JSON_NAME = "identity.json"
DIR_MODE = 0o700
FILE_MODE = 0o600

# El nombre va como etiqueta DNS en zeroconf (<nombre>.local.).
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclass(frozen=True)
class DeviceIdentity:
    name: str
    user_key: asyncssh.SSHKey
    host_key: asyncssh.SSHKey
    data_dir: Path


def default_data_dir() -> Path:
    """Carpeta de datos de Molink segun XDG; por defecto ~/.local/share/molink."""
    base = os.environ.get("XDG_DATA_HOME", "")
    root = Path(base) if base and Path(base).is_absolute() else Path.home() / ".local" / "share"
    return root / "molink"


def check_data_dir(path: Path) -> Path:
    """Rechaza una carpeta dentro de ~/.ssh: Molink no toca el SSH del sistema."""
    resolved = path.expanduser().resolve()
    ssh_dir = (Path.home() / ".ssh").resolve()
    if resolved == ssh_dir or ssh_dir in resolved.parents:
        raise ValueError("Molink no guarda nada en ~/.ssh")
    return resolved


def ensure_private_dir(path: Path) -> Path:
    """Crea la carpeta con 700 o la deja en 700 si ya existia con mas permisos."""
    path = check_data_dir(path)
    path.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    _tighten(path, DIR_MODE)
    return path


def _tighten(path: Path, mode: int) -> None:
    if path.stat().st_mode & 0o777 != mode:
        path.chmod(mode)
        logger.warning("Permisos corregidos a %o en %s", mode, path.name)


def write_private(path: Path, data: bytes) -> None:
    """Escribe con 600 desde el inicio y reemplaza de golpe (sin archivo a medias)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    with os.fdopen(fd, "wb") as file:
        file.write(data)
    os.replace(tmp, path)


def load_or_create_key(path: Path) -> asyncssh.SSHKey:
    """Lee la llave o la crea en ed25519 con 600, junto a su .pub."""
    ensure_private_dir(path.parent)
    if not path.exists():
        key = asyncssh.generate_private_key("ssh-ed25519")
        write_private(path, key.export_private_key())
        logger.info("Llave %s creada", path.name)
    _tighten(path, FILE_MODE)
    key = asyncssh.read_private_key(str(path))
    pub = path.with_name(path.name + ".pub")
    if not pub.exists():
        write_private(pub, key.export_public_key())
    _tighten(pub, FILE_MODE)
    return key


def check_device_name(name: str) -> str:
    """Nombre valido como etiqueta DNS: letras, digitos y guiones, de 1 a 63."""
    if not _NAME_PATTERN.match(name):
        raise ValueError("El nombre del equipo admite letras, digitos y guiones (1 a 63)")
    return name


def default_device_name() -> str:
    """El hostname del sistema llevado a etiqueta DNS valida."""
    label = socket.gethostname().split(".")[0]
    label = re.sub(r"[^A-Za-z0-9-]+", "-", label).strip("-")[:63].strip("-")
    return label or "molink"


def _read_name(path: Path) -> str | None:
    try:
        name = json.loads(path.read_text(encoding="utf-8")).get("name", "")
        return check_device_name(str(name))
    except (OSError, ValueError, AttributeError):
        return None


def save_device_name(data_dir: Path, name: str) -> str:
    """Guarda el nombre del equipo en identity.json (600)."""
    data_dir = ensure_private_dir(data_dir)
    name = check_device_name(name)
    payload = json.dumps({"name": name}, ensure_ascii=False, indent=2) + "\n"
    write_private(data_dir / IDENTITY_JSON_NAME, payload.encode("utf-8"))
    return name


def load_or_create_identity(data_dir: Path | None = None) -> DeviceIdentity:
    """Lee la identidad del equipo o la crea la primera vez."""
    data_dir = ensure_private_dir(data_dir or default_data_dir())
    name = _read_name(data_dir / IDENTITY_JSON_NAME)
    if name is None:
        name = save_device_name(data_dir, default_device_name())
        logger.info("Identidad del equipo creada")
    _tighten(data_dir / IDENTITY_JSON_NAME, FILE_MODE)
    return DeviceIdentity(
        name=name,
        user_key=load_or_create_key(data_dir / USER_KEY_NAME),
        host_key=load_or_create_key(data_dir / HOST_KEY_NAME),
        data_dir=data_dir,
    )
