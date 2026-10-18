"""Texto y rutas del lanzador de escritorio.

Logica pura: arma el ``.desktop`` segun la especificacion de freedesktop
(Cinnamon, GNOME, KDE...).
Las rutas absolutas se calculan al instalar; ninguna queda escrita en el
proyecto.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Igual que ``setDesktopFileName`` en ui/_00_ui_main.py: asi el escritorio
# asocia la ventana abierta con este lanzador.
APP_ID = "Molink"
ICON_SIZE = 256

# Caracteres que obligan a poner comillas en un argumento de Exec.
_RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")
# Dentro de comillas, estos se escapan con barra invertida.
_ESCAPED_IN_QUOTES = '"`$\\'


@dataclass(frozen=True, slots=True)
class LauncherPaths:
    shortcut_file: Path
    icon_file: Path


def launcher_paths(data_home: Path) -> LauncherPaths:
    """Rutas del lanzador dentro de ``data_home`` (normalmente ``~/.local/share``)."""
    return LauncherPaths(
        shortcut_file=data_home / "applications" / f"{APP_ID}.desktop",
        icon_file=data_home
        / "icons"
        / "hicolor"
        / f"{ICON_SIZE}x{ICON_SIZE}"
        / "apps"
        / f"{APP_ID}.png",
    )


def quote_exec_arg(arg: str) -> str:
    """Un argumento de Exec, entre comillas si hace falta."""
    if arg and not any(char in _RESERVED for char in arg):
        return arg
    escaped = "".join(f"\\{char}" if char in _ESCAPED_IN_QUOTES else char for char in arg)
    return f'"{escaped}"'


def escape_value(value: str) -> str:
    """Escapa un valor de tipo string del ``.desktop`` (la barra invertida va doble)."""
    return value.replace("\\", "\\\\")


def desktop_entry(python: Path, main_script: Path, icon_file: Path) -> str:
    """Contenido del ``.desktop`` que abre la app con el Python del proyecto."""
    exec_line = " ".join(quote_exec_arg(str(arg)) for arg in (python, main_script))
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={APP_ID}",
        "GenericName=Enlace entre dos equipos",
        "Comment=Comandos y chat con archivos entre dos equipos Linux de la red local",
        f"Exec={escape_value(exec_line)}",
        f"Path={escape_value(str(main_script.parent))}",
        f"Icon={escape_value(str(icon_file))}",
        "Terminal=false",
        "Categories=Network;RemoteAccess;",
        "Keywords=ssh;red;chat;archivos;consola;",
        f"StartupWMClass={APP_ID}",
        "StartupNotify=true",
    ]
    return "\n".join(lines) + "\n"
