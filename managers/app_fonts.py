"""Carga las letras de la interfaz (IBM Plex Sans y Mono, OFL).

La ventana principal la llama una vez y le pasa el resultado al tema
(``ui.theme``): la UI no lee archivos. Sin los archivos, la app
sigue con la letra del sistema.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QFontDatabase

from paths import FONTS_DIR

logger = logging.getLogger(__name__)

SANS_FAMILY = "IBM Plex Sans"
MONO_FAMILY = "IBM Plex Mono"


def load_app_fonts(fonts_dir: Path = FONTS_DIR) -> tuple[str, str]:
    """Registra cada ``.ttf`` de ``fonts_dir`` en Qt; ``(sans, mono)``, vacia la que falte."""
    families: set[str] = set()
    for path in sorted(fonts_dir.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            logger.warning("No se pudo cargar la letra %s", path.name)
            continue
        families.update(QFontDatabase.applicationFontFamilies(font_id))
    sans = SANS_FAMILY if SANS_FAMILY in families else ""
    mono = MONO_FAMILY if MONO_FAMILY in families else ""
    if not sans or not mono:
        logger.warning("Faltan letras del tema en %s; se usa la del sistema", fonts_dir)
    return sans, mono
