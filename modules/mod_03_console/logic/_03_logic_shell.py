"""Lo que hace de la consola un shell: carpeta de trabajo, historial y sudo.

Logica pura. Cada comando corre en un proceso nuevo alla, asi que la carpeta se
arrastra de aqui: el guion entra a la ultima carpeta, corre el comando y, al
salir, deja en stderr una marca con $PWD y $HOME que ShellMarkFilter quita de
la salida. La contrasena de sudo nunca entra al guion: va por stdin.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

STDERR = "stderr"  # nombre del flujo como lo da el cliente SSH
MARK = b"\x1eMOLINK:"
SEPARATOR = b"\x1e"
HISTORY_SIZE = 100
SUDO_WORD = re.compile(r"(^|[\s;&|()`])sudo(\s|$)")

_TRAP = 'trap \'printf "\\036MOLINK:%s\\036%s\\036" "$PWD" "$HOME" >&2\' EXIT'
_SUDO = "sudo() { command sudo -S -p '' \"$@\"; }"


def is_clear(command: str) -> bool:
    """clear no tiene terminal que limpiar alla: lo hace la consola aqui."""
    return command.strip() == "clear"


def needs_password(command: str) -> bool:
    """True si el comando llama a sudo: antes de correrlo se pide la contrasena."""
    return SUDO_WORD.search(command) is not None


def wrap_command(command: str, cwd: str, with_sudo: bool) -> str:
    """Guion que corre command en cwd (o en la carpeta personal) y avisa donde quedo."""
    enter = f"cd -- {shlex.quote(cwd)} 2>/dev/null || cd" if cwd else "cd"
    lines = [enter, _TRAP]
    if with_sudo:
        lines.append(_SUDO)
    lines.append(command)
    return "\n".join(lines)


def short_path(path: str, home: str) -> str:
    """La carpeta como la escribe un shell: la personal es ~."""
    if not path:
        return "~"
    if home and path == home:
        return "~"
    if home and path.startswith(home.rstrip("/") + "/"):
        return "~" + path[len(home.rstrip("/")) :]
    return path


@dataclass(frozen=True)
class Place:
    """Donde quedo el comando en el otro equipo."""

    cwd: str
    home: str


class ShellMarkFilter:
    """Quita de stderr la marca de salida, aunque llegue partida en varios trozos."""

    def __init__(self) -> None:
        self._held = b""  # posible comienzo de la marca, aun sin confirmar
        self._tail: bytes | None = None  # desde la marca en adelante

    def feed(self, stream: str, data: bytes) -> bytes:
        if stream != STDERR:
            return data
        if self._tail is not None:
            self._tail += data
            return b""
        buf = self._held + data
        start = buf.find(MARK)
        if start >= 0:
            self._held = b""
            self._tail = buf[start:]
            return buf[:start]
        keep = _partial_mark(buf)
        self._held = buf[len(buf) - keep :] if keep else b""
        return buf[: len(buf) - keep]

    def finish(self) -> tuple[bytes, Place | None]:
        """Lo que quedo retenido para mostrar y la carpeta, si la marca llego entera."""
        held, tail = self._held, self._tail
        self._held, self._tail = b"", None
        if tail is None:
            return held, None
        parts = tail[len(MARK) :].split(SEPARATOR)
        if len(parts) < 3:
            return tail, None
        cwd, home, rest = parts[0], parts[1], SEPARATOR.join(parts[2:])
        place = Place(cwd.decode("utf-8", "replace"), home.decode("utf-8", "replace"))
        return rest, place


def _partial_mark(buf: bytes) -> int:
    """Largo del final de buf que coincide con el comienzo de MARK."""
    for size in range(min(len(MARK) - 1, len(buf)), 0, -1):
        if MARK.startswith(buf[-size:]):
            return size
    return 0


class CommandHistory:
    """Comandos ya corridos, del mas viejo al mas nuevo; flechas como en un shell."""

    def __init__(self, size: int = HISTORY_SIZE) -> None:
        self._items: list[str] = []
        self._size = size
        self._index = 0  # len(_items) = la linea nueva
        self._draft = ""

    @property
    def items(self) -> tuple[str, ...]:
        return tuple(self._items)

    def add(self, command: str) -> None:
        command = command.strip()
        if command and (not self._items or self._items[-1] != command):
            self._items.append(command)
            del self._items[: -self._size]
        self._index = len(self._items)
        self._draft = ""

    def older(self, current: str) -> str:
        """Flecha arriba: el comando anterior; en el primero se queda."""
        if self._index == len(self._items):
            self._draft = current
        self._index = max(self._index - 1, 0)
        return self._items[self._index] if self._items else current

    def newer(self) -> str:
        """Flecha abajo: el siguiente; despues del ultimo vuelve lo que se escribia."""
        self._index = min(self._index + 1, len(self._items))
        if self._index == len(self._items):
            return self._draft
        return self._items[self._index]
