"""Responsabilidad unica: pasar un archivo al otro equipo por SFTP sin pisar nada.

Lado que recibe: el servidor SSH abre un SFTP encerrado en la carpeta de
llegada (por defecto <Descargas>/Molink) que solo deja crear archivos .part
nuevos, renombrarlos a un nombre que no exista y borrar .part a medias. No
sobrescribe, no crea carpetas ni enlaces y no sale de la carpeta.

Lado que envia: send_file elige un nombre libre (nombre (1).ext, ...), abre
nombre.part con el tamano total en sus atributos, escribe bloques propios con
avance y al terminar lo renombra. Si la tarea se cancela o la red se cae,
borra el .part si todavia puede.

El que recibe se entera por on_incoming: un IncomingEvent al empezar (con el
total que viaja en los atributos), avisos de bytes como mucho cada
PROGRESS_EVERY_S, uno al renombrar (DONE) y uno si se corta (CUT: se cerro
incompleto, se borro el .part o se cayo la conexion). Cada evento lleva la
llave publica del que envia para saber de que equipo viene.

En los logs solo va el tamano: el nombre de un archivo tambien es contenido.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath

import asyncssh

from logic._00_logic_platform import sftp_local_path
from services.service_ssh_server import PEER_KEY_INFO

logger = logging.getLogger(__name__)

PART_SUFFIX = ".part"
INBOX_NAME = "Molink"
MAX_NAME_TRIES = 1000
# En SFTP v3 no hay codigo de "ya existe": llega como SFTPFailure con este texto.
ALREADY_EXISTS = "El archivo ya existe"
# Bloques chicos y pocos en vuelo: entre dos asyncssh se negocian 4 MiB por
# escritura y 128 en vuelo, y por una wifi lenta el avance no se mueve en
# decenas de segundos. 256 KiB x 16 = 4 MiB en camino.
BLOCK_SIZE = 256 * 1024
MAX_REQUESTS = 16
# Sin avance en este tiempo, el envio se da por detenido.
STALL_S = 30.0
CHECK_S = 1.0
REMOVE_TIMEOUT_S = 5.0
# El que recibe no necesita un aviso por bloque: con 16 en vuelo llegarian decenas por segundo.
PROGRESS_EVERY_S = 0.2
_USER_DIRS = Path.home() / ".config" / "user-dirs.dirs"

# Recibe los bytes enviados y el total.
ProgressCallback = Callable[[int, int], None]


class IncomingKind(Enum):
    START = "start"
    PROGRESS = "progress"
    DONE = "done"
    CUT = "cut"


@dataclass(frozen=True)
class IncomingEvent:
    """Un archivo que llega: name es el nombre sin .part (el final en DONE)."""

    transfer_id: int
    kind: IncomingKind
    name: str
    received: int
    total: int | None  # None si el que envia no mando el tamano
    peer_key: bytes = b""
    peer: str = ""  # nombre del equipo emparejado; lo pone service_link


IncomingCallback = Callable[[IncomingEvent], None]
_transfer_ids = itertools.count(1)

_WRITE_FLAGS = asyncssh.FXF_WRITE | asyncssh.FXF_APPEND | asyncssh.FXF_CREAT | asyncssh.FXF_TRUNC


def default_inbox(user_dirs: Path = _USER_DIRS) -> Path:
    """<XDG_DOWNLOAD_DIR>/Molink; sin user-dirs.dirs, ~/Downloads/Molink."""
    home = Path.home()
    downloads = home / "Downloads"
    try:
        text = user_dirs.read_text(encoding="utf-8")
    except OSError:
        text = ""
    match = re.search(r'^XDG_DOWNLOAD_DIR="(.+)"\s*$', text, re.MULTILINE)
    if match:
        downloads = Path(match.group(1).replace("$HOME", str(home)))
    return downloads / INBOX_NAME


def ensure_inbox(inbox: Path) -> Path:
    """Crea la carpeta de llegada si falta; el servidor la crea al primer envio."""
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


def _already_exists(exc: asyncssh.SFTPError) -> bool:
    if isinstance(exc, asyncssh.SFTPFileAlreadyExists):
        return True
    return isinstance(exc, asyncssh.SFTPFailure) and exc.reason == ALREADY_EXISTS


def _is_part(path: bytes) -> bool:
    return path.endswith(PART_SUFFIX.encode())


def _bare_name(path: bytes) -> str:
    return PurePosixPath(os.fsdecode(path)).name.removesuffix(PART_SUFFIX)


@dataclass
class _Incoming:
    """Un .part que se esta recibiendo; file_obj es None ya cerrado y a la espera del rename."""

    transfer_id: int
    name: str
    total: int | None
    file_obj: object | None
    peer_key: bytes
    received: int = 0
    last_emit: float = field(default_factory=time.monotonic)


class TransferStalled(TimeoutError):
    """El envio no avanzo en STALL_S segundos."""


class InboxSFTPServer(asyncssh.SFTPServer):
    """SFTP encerrado en la carpeta de llegada: escribe solo .part nuevos."""

    def __init__(
        self,
        chan: asyncssh.SSHServerChannel,
        inbox: Path,
        on_incoming: IncomingCallback | None = None,
    ):
        super().__init__(chan, chroot=str(ensure_inbox(inbox)).encode())
        self._on_incoming = on_incoming
        self._incoming: dict[bytes, _Incoming] = {}  # por ruta del .part

    def _local(self, path: bytes) -> str:
        return sftp_local_path(os.fsdecode(self.map_path(path)))

    def _emit(self, item: _Incoming, kind: IncomingKind, name: str | None = None) -> None:
        item.last_emit = time.monotonic()
        if self._on_incoming is None:
            return
        event = IncomingEvent(
            item.transfer_id, kind, name or item.name, item.received, item.total, item.peer_key
        )
        try:
            self._on_incoming(event)
        except Exception:
            # Un fallo de quien escucha no debe cortar la recepcion.
            logger.exception("Fallo el aviso de un archivo entrante")

    def _finish(self, path: bytes, kind: IncomingKind, name: str | None = None) -> None:
        item = self._incoming.pop(path, None)
        if item is not None:
            self._emit(item, kind, name)

    def open(self, path: bytes, pflags: int, attrs: asyncssh.SFTPAttrs):
        if not pflags & _WRITE_FLAGS:
            return super().open(path, pflags, attrs)
        if not _is_part(path):
            raise asyncssh.SFTPPermissionDenied("Molink solo escribe archivos .part")
        if os.path.lexists(self._local(path)):
            raise asyncssh.SFTPFileAlreadyExists(ALREADY_EXISTS)
        # O_EXCL: si otro lo crea entre la comprobacion y la apertura, falla.
        file_obj = super().open(path, pflags | asyncssh.FXF_EXCL, attrs)
        # Se toma al abrir: cuando la conexion se cae ya no se puede preguntar.
        peer_key = self.connection.get_extra_info(PEER_KEY_INFO, b"")
        item = _Incoming(next(_transfer_ids), _bare_name(path), attrs.size, file_obj, peer_key)
        self._incoming[path] = item
        self._emit(item, IncomingKind.START)
        return file_obj

    def _tracked(self, file_obj: object) -> tuple[bytes, _Incoming] | None:
        for path, item in self._incoming.items():
            if item.file_obj is file_obj:
                return path, item
        return None

    def write(self, file_obj: object, offset: int, data: bytes):
        written = super().write(file_obj, offset, data)
        tracked = self._tracked(file_obj)
        if tracked is not None:
            item = tracked[1]
            item.received += len(data)
            if time.monotonic() - item.last_emit >= PROGRESS_EVERY_S:
                self._emit(item, IncomingKind.PROGRESS)
        return written

    def close(self, file_obj: object) -> None:
        super().close(file_obj)
        tracked = self._tracked(file_obj)
        if tracked is None:
            return
        path, item = tracked
        item.file_obj = None
        if item.total is not None and item.received < item.total:
            self._finish(path, IncomingKind.CUT)
        # Completo: queda a la espera del rename (DONE) o del remove (CUT).

    def exit(self) -> None:
        # Al caer la conexion asyncssh cierra los abiertos y llama a exit.
        for path in list(self._incoming):
            self._finish(path, IncomingKind.CUT)

    def rename(self, oldpath: bytes, newpath: bytes) -> None:
        if not _is_part(oldpath) or _is_part(newpath):
            raise asyncssh.SFTPPermissionDenied("Molink solo renombra un .part a su nombre")
        target = self._local(newpath)
        if os.path.lexists(target):
            raise asyncssh.SFTPFileAlreadyExists(ALREADY_EXISTS)
        # link + unlink falla si el destino aparece entre medias; rename lo pisaria.
        source = self._local(oldpath)
        os.link(source, target)
        os.unlink(source)
        logger.info("Archivo recibido de %s bytes", os.path.getsize(target))
        self._finish(oldpath, IncomingKind.DONE, _bare_name(newpath))

    def posix_rename(self, oldpath: bytes, newpath: bytes) -> None:
        raise asyncssh.SFTPPermissionDenied("Molink no sobrescribe archivos")

    def remove(self, path: bytes) -> None:
        if not _is_part(path):
            raise asyncssh.SFTPPermissionDenied("Molink solo borra archivos .part")
        super().remove(path)
        self._finish(path, IncomingKind.CUT)

    def _denied(self, *args, **kwargs):
        raise asyncssh.SFTPPermissionDenied("Molink no permite esta operacion")

    mkdir = rmdir = symlink = link = setstat = fsetstat = _denied


def inbox_sftp_factory(
    inbox: Path, on_incoming: IncomingCallback | None = None
) -> Callable[[asyncssh.SSHServerChannel], InboxSFTPServer]:
    return lambda chan: InboxSFTPServer(chan, inbox, on_incoming)


def candidate_names(name: str):
    """nombre.ext, nombre (1).ext, nombre (2).ext, ..."""
    path = PurePosixPath(name)
    stem, suffix = path.stem, path.suffix
    yield name
    for index in range(1, MAX_NAME_TRIES):
        yield f"{stem} ({index}){suffix}"


async def _free_name(sftp: asyncssh.SFTPClient, name: str) -> str:
    for candidate in candidate_names(name):
        if not await sftp.exists(candidate) and not await sftp.exists(candidate + PART_SUFFIX):
            return candidate
    raise FileExistsError(f"No hay un nombre libre para {name}")


async def send_file(
    conn: asyncssh.SSHClientConnection,
    local_path: Path,
    on_progress: ProgressCallback | None = None,
    stall_s: float = STALL_S,
) -> str:
    """Envia local_path a la carpeta de llegada del otro equipo; devuelve el nombre alla.

    Nunca pisa: si el nombre esta ocupado usa el siguiente libre. Cancelar la
    tarea borra el .part del otro lado; si no avanza en stall_s segundos,
    tambien, y sale TransferStalled.
    """
    if not local_path.is_file():
        raise FileNotFoundError(local_path)

    async with conn.start_sftp_client() as sftp:
        for _ in range(MAX_NAME_TRIES):
            name = await _free_name(sftp, local_path.name)
            part = name + PART_SUFFIX
            try:
                await _put_watched(conn, sftp, local_path, part, on_progress, stall_s)
            except asyncssh.SFTPError as exc:
                if _already_exists(exc):
                    continue  # otro envio tomo ese nombre entre medias
                await _remove_quietly(sftp, part)
                raise
            except BaseException:
                await _remove_quietly(sftp, part)
                raise
            try:
                await sftp.rename(part, name)
            except asyncssh.SFTPError as exc:
                await _remove_quietly(sftp, part)
                if _already_exists(exc):
                    continue
                raise
            logger.info("Archivo enviado de %s bytes", local_path.stat().st_size)
            return name
    raise FileExistsError(f"No hay un nombre libre para {local_path.name}")


async def _put_watched(
    conn: asyncssh.SSHClientConnection,
    sftp: asyncssh.SFTPClient,
    local_path: Path,
    part: str,
    on_progress: ProgressCallback | None,
    stall_s: float,
) -> None:
    """Sube en bloques chicos; corta con TransferStalled si no avanza en stall_s.

    Al cancelar, asyncssh espera las respuestas pendientes; si el otro lado no
    contesta en REMOVE_TIMEOUT_S, se aborta la conexion para no quedar colgado.
    """
    last = [time.monotonic()]

    def progress(_src, _dst, sent: int, total: int) -> None:
        last[0] = time.monotonic()
        if on_progress is not None:
            on_progress(sent, total)

    task = asyncio.ensure_future(_upload(sftp, local_path, part, progress))
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=CHECK_S)
            if done:
                task.result()
                return
            if time.monotonic() - last[0] > stall_s:
                logger.warning("Envio detenido: sin avance en %s s", stall_s)
                raise TransferStalled(f"Sin avance en {stall_s:.0f} s")
    finally:
        if not task.done():
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=REMOVE_TIMEOUT_S)
            if not done:
                logger.warning("El otro equipo no responde: se corta la conexion")
                conn.abort()
                await asyncio.wait({task}, timeout=REMOVE_TIMEOUT_S)


async def _upload(
    sftp: asyncssh.SFTPClient,
    local_path: Path,
    part: str,
    progress: Callable[[str, str, int, int], None],
) -> None:
    """Como put, pero abre el .part con el tamano total para que el que recibe lo sepa.

    MAX_REQUESTS escrituras de BLOCK_SIZE en vuelo; el avance cuenta las ya
    confirmadas. Al cancelar o fallar, espera las pendientes REMOVE_TIMEOUT_S.
    """
    total = local_path.stat().st_size
    attrs = asyncssh.SFTPAttrs(size=total)
    sent = 0
    pending: set[asyncio.Future] = set()
    try:
        async with await sftp.open(part, "wb", attrs, encoding=None) as remote:
            progress(str(local_path), part, 0, total)
            with local_path.open("rb") as source:
                offset = 0
                while offset < total or pending:
                    while offset < total and len(pending) < MAX_REQUESTS:
                        block = source.read(BLOCK_SIZE)
                        if not block:
                            break
                        write = asyncio.ensure_future(remote.write(block, offset))
                        write.add_done_callback(_retrieve)
                        pending.add(write)
                        offset += len(block)
                    if not pending:
                        break
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for write in done:
                        sent += write.result()
                        progress(str(local_path), part, sent, total)
    finally:
        # Cancelar una escritura a medias deja tareas internas de asyncssh con
        # el error sin recoger: primero se dejan terminar.
        if pending:
            _, pending = await asyncio.wait(pending, timeout=REMOVE_TIMEOUT_S)
        for write in pending:
            write.cancel()


def _retrieve(write: asyncio.Future) -> None:
    """Recoge el error de una escritura: si fallan varias, solo se lanza la primera."""
    if not write.cancelled():
        write.exception()


async def _remove_quietly(sftp: asyncssh.SFTPClient, part: str) -> None:
    """Borra el .part alla; si la conexion no responde, se rinde a los REMOVE_TIMEOUT_S."""
    with contextlib.suppress(asyncssh.Error, OSError, asyncio.CancelledError):
        await asyncio.wait_for(sftp.remove(part), REMOVE_TIMEOUT_S)
