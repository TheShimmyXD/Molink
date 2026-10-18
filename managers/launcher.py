"""Instala el lanzador de escritorio de Molink.

Escribe el icono del sello en PNG y el ``.desktop`` en la carpeta de datos del
usuario (sin sudo; se quita borrando esos dos archivos). Recibe el icono ya
dibujado: este gestor no importa la UI.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtGui import QPixmap

from logic._00_logic_launcher import LauncherPaths, desktop_entry, launcher_paths
from paths import ROOT

logger = logging.getLogger(__name__)


def default_data_home() -> Path:
    """``$XDG_DATA_HOME`` o, si no esta definido, ``~/.local/share``."""
    value = os.environ.get("XDG_DATA_HOME", "")
    return Path(value) if value else Path.home() / ".local" / "share"


def install_launcher(icon: QPixmap, data_home: Path | None = None) -> LauncherPaths:
    """Escribe el PNG y el ``.desktop``; los reemplaza si ya existen."""
    if not sys.platform.startswith("linux"):
        raise OSError("El lanzador solo se instala en Linux; abre Molink con python main.py.")
    paths = launcher_paths(data_home or default_data_home())
    paths.icon_file.parent.mkdir(parents=True, exist_ok=True)
    if not icon.save(str(paths.icon_file), "PNG"):
        raise OSError(f"No se pudo guardar el icono en {paths.icon_file}")
    paths.shortcut_file.parent.mkdir(parents=True, exist_ok=True)
    entry = desktop_entry(Path(sys.executable), ROOT / "main.py", paths.icon_file)
    paths.shortcut_file.write_text(entry, encoding="utf-8")
    paths.shortcut_file.chmod(0o755)
    logger.info("Lanzador instalado en %s (icono en %s)", paths.shortcut_file, paths.icon_file)
    return paths
