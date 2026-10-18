from __future__ import annotations

import sys
from pathlib import Path

# -- Raíz del proyecto -----------------------------------------
# Con PyInstaller los recursos se extraen en sys._MEIPASS.

ROOT = (
    Path(sys._MEIPASS)  # type: ignore[attr-defined]
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)

# -- Directorios -----------------------------------------------

RESOURCES_DIR = ROOT / "resources"
JSON_DIR = RESOURCES_DIR / "json"
QUERIES_DIR = RESOURCES_DIR / "queries"
LOG_DIR = RESOURCES_DIR / "logs"

# -- JSON ------------------------------------------------------

# Configuración de la aplicación (versionada, sin datos sensibles).
APP_SETTINGS_JSON = JSON_DIR / "app_settings.json"

# -- Letras e iconos de la interfaz (licencias OFL y MIT) ------

FONTS_DIR = RESOURCES_DIR / "fonts"
ICONS_DIR = RESOURCES_DIR / "icons"
ICON_FONT = ICONS_DIR / "phosphor-regular.woff2"
ICON_MAP = ICONS_DIR / "phosphor-regular.json"
