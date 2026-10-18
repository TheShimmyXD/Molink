"""Lista de equipos emparejados: paired.json (600) en la carpeta de datos.

Cada entrada guarda el nombre del otro equipo y sus dos llaves publicas: con
la de usuario se le deja entrar a nuestro servidor y con la de host se
reconoce el suyo. Asi no hace falta ~/.ssh/known_hosts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import asyncssh

from services.service_identity import check_device_name, ensure_private_dir, write_private

logger = logging.getLogger(__name__)

PAIRED_JSON_NAME = "paired.json"
KEY_ALGORITHM = "ssh-ed25519"


def parse_public_key(text: str) -> asyncssh.SSHKey:
    """Llave publica OpenSSH en una linea; solo ed25519."""
    key = asyncssh.import_public_key(text)
    if key.get_algorithm() != KEY_ALGORITHM:
        raise ValueError("Solo se aceptan llaves ed25519")
    return key


def _canonical(key: asyncssh.SSHKey) -> str:
    """La llave sin comentario, para comparar por contenido."""
    return " ".join(key.export_public_key().decode("ascii").split()[:2])


@dataclass(frozen=True)
class PeerRecord:
    name: str
    user_key: str
    host_key: str
    paired_at: str = ""

    @classmethod
    def build(cls, name: str, user_key: str, host_key: str, paired_at: str = "") -> PeerRecord:
        """Valida el nombre y las dos llaves y las deja en forma canonica."""
        user = parse_public_key(user_key)
        host = parse_public_key(host_key)
        if user.public_data == host.public_data:
            raise ValueError("La llave de usuario y la de host deben ser distintas")
        return cls(check_device_name(name), _canonical(user), _canonical(host), paired_at)

    def user_fingerprint(self) -> str:
        return asyncssh.import_public_key(self.user_key).get_fingerprint()

    def host_fingerprint(self) -> str:
        return asyncssh.import_public_key(self.host_key).get_fingerprint()


def load_paired(data_dir: Path) -> list[PeerRecord]:
    """Lee la lista; una entrada danada se salta con un aviso, sin tumbar el resto."""
    path = data_dir / PAIRED_JSON_NAME
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw.get("peers", []) if isinstance(raw, dict) else []
    except (OSError, ValueError):
        logger.warning("Lista de emparejados ilegible; se trata como vacia")
        return []
    peers: list[PeerRecord] = []
    for entry in entries:
        try:
            peers.append(
                PeerRecord.build(
                    entry["name"], entry["user_key"], entry["host_key"], entry.get("paired_at", "")
                )
            )
        except (KeyError, TypeError, ValueError, asyncssh.KeyImportError):
            logger.warning("Entrada de emparejado invalida; se omite")
    return peers


def save_paired(data_dir: Path, peers: list[PeerRecord]) -> None:
    data_dir = ensure_private_dir(data_dir)
    payload = {"peers": [asdict(peer) for peer in peers]}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    write_private(data_dir / PAIRED_JSON_NAME, text.encode("utf-8"))


def add_paired(data_dir: Path, peer: PeerRecord) -> list[PeerRecord]:
    """Agrega o reemplaza: un mismo nombre o una misma llave de host es el mismo equipo."""
    if not peer.paired_at:
        peer = replace(peer, paired_at=datetime.now(UTC).isoformat(timespec="seconds"))
    peers = [
        old
        for old in load_paired(data_dir)
        if old.name != peer.name and old.host_key != peer.host_key
    ]
    peers.append(peer)
    save_paired(data_dir, peers)
    logger.info("Equipo emparejado: %s", peer.name)
    return peers


def remove_paired(data_dir: Path, name: str) -> bool:
    peers = load_paired(data_dir)
    kept = [peer for peer in peers if peer.name != name]
    if len(kept) == len(peers):
        return False
    save_paired(data_dir, kept)
    logger.info("Emparejamiento quitado: %s", name)
    return True


def authorized_user_keys(data_dir: Path) -> list[asyncssh.SSHKey]:
    """Las llaves de usuario que nuestro servidor debe aceptar."""
    return [asyncssh.import_public_key(peer.user_key) for peer in load_paired(data_dir)]
