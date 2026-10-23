"""Texto y rutas del lanzador de escritorio.

Logica pura: arma el ``.desktop`` segun la especificacion de freedesktop
(Cinnamon, GNOME, KDE...) y, en Windows, el guion de PowerShell que crea el
acceso directo ``.lnk`` del menu Inicio.
Las rutas absolutas se calculan al instalar; ninguna queda escrita en el
proyecto.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath

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


def windows_launcher_paths(appdata: PurePath, local_appdata: PurePath) -> LauncherPaths:
    """Rutas en Windows: el ``.lnk`` en el menu Inicio del usuario y el ``.ico``
    junto a los datos de Molink (``%LOCALAPPDATA%\\Molink``)."""
    programs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return LauncherPaths(
        shortcut_file=programs / f"{APP_ID}.lnk",
        icon_file=local_appdata / APP_ID / f"{APP_ID}.ico",
    )


def quote_powershell(value: str) -> str:
    """Cadena literal de PowerShell: entre comillas simples, la comilla va doble."""
    return "'" + value.replace("'", "''") + "'"


def shortcut_script(
    shortcut_file: PurePath, pythonw: PurePath, main_script: PurePath, icon_file: PurePath
) -> str:
    """Guion de PowerShell que crea (o reemplaza) el ``.lnk`` con ``WScript.Shell``.

    Abre la app con ``pythonw.exe`` para que no salga una ventana de consola.
    """
    arguments = f'"{main_script}"'
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$shell = New-Object -ComObject WScript.Shell",
        f"$link = $shell.CreateShortcut({quote_powershell(str(shortcut_file))})",
        f"$link.TargetPath = {quote_powershell(str(pythonw))}",
        f"$link.Arguments = {quote_powershell(arguments)}",
        f"$link.WorkingDirectory = {quote_powershell(str(main_script.parent))}",
        f"$link.IconLocation = {quote_powershell(f'{icon_file},0')}",
        f"$link.Description = {quote_powershell('Enlace entre dos equipos de la red local')}",
        "$link.Save()",
    ]
    return "\n".join(lines) + "\n"


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
