"""Sistema de este equipo y del otro: Linux o Windows.

Logica pura. El anuncio de zeroconf lleva os=linux u os=windows; un equipo
que no la lleva (Molink 0.1.0) es Linux. En Windows el servidor corre lo que
llega en PowerShell con la salida en UTF-8, sin ventana y en su propio grupo
de procesos, y lo termina con taskkill sobre todo el arbol. El guion termina
como sh: con el codigo del ultimo programa, o 1 si fallo un cmdlet.
"""

from __future__ import annotations

import subprocess
import sys

OS_LINUX = "linux"
OS_WINDOWS = "windows"
OS_KEY = "os"

# Lo primero del guion: se borra a si mismo (PowerShell ya lo leyo entero), sin
# barras de progreso y en UTF-8 (sin esto escribe en la pagina OEM, cp850).
_PS_HEAD = (
    "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
    "$ProgressPreference = 'SilentlyContinue'\n"
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $OutputEncoding = [Text.Encoding]::UTF8\n"
)
# Lo ultimo: el codigo del programa que fallo, 1 si fallo un cmdlet, 0 si no.
_PS_TAIL = "\nif (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE } else { exit 1 } }\nexit 0\n"

# Sin ventana de consola (la app no tiene una) y con su propio grupo de procesos.
WINDOWS_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(
    subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
)


def local_os(platform: str = sys.platform) -> str:
    """Sistema de este equipo como lo anuncia Molink."""
    return OS_WINDOWS if platform == "win32" else OS_LINUX


def is_windows(platform: str = sys.platform) -> bool:
    return local_os(platform) == OS_WINDOWS


def peer_os(value: str | bytes | None) -> str:
    """Sistema del otro equipo segun su anuncio; sin dato o desconocido es Linux."""
    if isinstance(value, bytes):
        value = value.decode("ascii", "replace")
    return OS_WINDOWS if value == OS_WINDOWS else OS_LINUX


def powershell_script(command: str) -> str:
    """Guion .ps1 que corre command y sale con su codigo."""
    return _PS_HEAD + command + _PS_TAIL


def powershell_file_args(path: str) -> list[str]:
    """Orden que corre el .ps1 sin perfil; Bypass vale solo para este proceso."""
    return [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        path,
    ]


def taskkill_args(pid: int) -> list[str]:
    """Orden que termina el proceso pid y todos sus hijos."""
    return ["taskkill.exe", "/T", "/F", "/PID", str(pid)]
