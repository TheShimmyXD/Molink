"""Carga la fuente de iconos de la interfaz (Phosphor, MIT) y su mapa de codigos.

La ventana principal la llama una vez y le pasa el resultado a ``ui.blocks.icons``:
la UI no lee archivos.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtGui import QFontDatabase

from paths import ICON_FONT, ICON_MAP

logger = logging.getLogger(__name__)


def load_icon_font(font_path: Path = ICON_FONT, map_path: Path = ICON_MAP) -> tuple[str, dict]:
    """Familia de la fuente cargada en Qt y ``nombre -> codigo``; vacios si falla."""
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    try:
        codes = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("No se pudo leer el mapa de iconos %s", map_path)
        codes = {}
    if not families:
        logger.warning("No se pudo cargar la fuente de iconos %s", font_path)
        return "", {}
    return families[0], codes
