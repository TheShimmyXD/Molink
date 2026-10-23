"""Instala el lanzador de escritorio de Molink.

En Linux escribe el icono del sello en PNG y el ``.desktop`` en la carpeta de
datos del usuario; en Windows, el icono en ICO y un ``.lnk`` en el menu Inicio
del usuario. Sin sudo ni administrador: se quita borrando esos dos archivos.
Recibe el icono ya dibujado: este gestor no importa la UI.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QPixmap

from logic._00_logic_launcher import (
    LauncherPaths,
    desktop_entry,
    launcher_paths,
    shortcut_script,
    windows_launcher_paths,
)
from logic._00_logic_platform import is_windows
from paths import ROOT

logger = logging.getLogger(__name__)

_POWERSHELL_TIMEOUT_S = 60


def default_data_home() -> Path:
    """``$XDG_DATA_HOME`` o, si no esta definido, ``~/.local/share``."""
    value = os.environ.get("XDG_DATA_HOME", "")
    return Path(value) if value else Path.home() / ".local" / "share"


def _windows_folder(variable: str, fallback: str) -> Path:
    """``%APPDATA%`` o ``%LOCALAPPDATA%``; si falta, la ruta de siempre bajo el perfil."""
    value = os.environ.get(variable, "")
    return Path(value) if value else Path.home() / "AppData" / fallback


def _save_icon(icon: QPixmap, path: Path, image_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not icon.save(str(path), image_format):
        raise OSError(f"No se pudo guardar el icono en {path}")


def install_launcher(icon: QPixmap, data_home: Path | None = None) -> LauncherPaths:
    """Escribe el icono y el acceso; los reemplaza si ya existen."""
    if is_windows():
        return _install_windows(icon)
    if not sys.platform.startswith("linux"):
        raise OSError(
            "El lanzador solo se instala en Linux y Windows; abre Molink con python main.py."
        )
    paths = launcher_paths(data_home or default_data_home())
    _save_icon(icon, paths.icon_file, "PNG")
    paths.shortcut_file.parent.mkdir(parents=True, exist_ok=True)
    entry = desktop_entry(Path(sys.executable), ROOT / "main.py", paths.icon_file)
    paths.shortcut_file.write_text(entry, encoding="utf-8")
    paths.shortcut_file.chmod(0o755)
    logger.info("Lanzador instalado en %s (icono en %s)", paths.shortcut_file, paths.icon_file)
    return paths


def _install_windows(icon: QPixmap) -> LauncherPaths:
    paths = windows_launcher_paths(
        _windows_folder("APPDATA", "Roaming"), _windows_folder("LOCALAPPDATA", "Local")
    )
    _save_icon(icon, paths.icon_file, "ICO")
    paths.shortcut_file.parent.mkdir(parents=True, exist_ok=True)
    # pythonw.exe abre la app sin ventana de consola; si no esta, se usa el mismo Python.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    script = shortcut_script(paths.shortcut_file, pythonw, ROOT / "main.py", paths.icon_file)
    # -EncodedCommand va en UTF-16: asi una ruta con tildes o comillas llega intacta.
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    args = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        encoded,
    ]
    try:
        result = subprocess.run(
            args, capture_output=True, timeout=_POWERSHELL_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OSError(f"No se pudo crear el acceso directo: {exc}") from exc
    if result.returncode != 0:
        raise OSError(f"PowerShell no creo el acceso directo (codigo {result.returncode}).")
    logger.info("Acceso directo en %s (icono en %s)", paths.shortcut_file, paths.icon_file)
    return paths
