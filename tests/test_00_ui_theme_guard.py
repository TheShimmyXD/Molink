"""Ningun color ni hoja de estilo fuera del tema: los modulos piden rol, tono o pieza."""

from __future__ import annotations

import re
from pathlib import Path

from paths import ROOT
from ui.theme import DARK, LIGHT, next_theme, resolve_theme

THEME_FILE = ROOT / "ui" / "theme.py"
FORBIDDEN = {
    "color hexadecimal": re.compile(r"#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b"),
    "rgb()": re.compile(r"\brgba?\("),
    "QColor con numeros": re.compile(r"QColor\(\s*\d"),
    "color fijo de Qt": re.compile(r"Qt\.(?:GlobalColor\.)?(?:red|green|blue|black|white|gray)\b"),
    "setStyleSheet": re.compile(r"\.setStyleSheet\("),
}


def _ui_files() -> list[Path]:
    files = list((ROOT / "ui").rglob("*.py"))
    for layer in ("ui", "dialogs"):
        files += (ROOT / "modules").glob(f"mod_*/{layer}/*.py")
    return sorted(path for path in files if path != THEME_FILE)


def test_the_scan_sees_the_interface():
    names = {path.name for path in _ui_files()}
    assert {"_00_ui_main.py", "_00_ui_sidebar.py", "icons.py", "logo.py"} <= names


def test_no_colors_outside_the_theme():
    found = []
    for path in _ui_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = "" if line.lstrip().startswith("#") else line
            for name, pattern in FORBIDDEN.items():
                if pattern.search(code) and path.name != "theme_qss.py":
                    found.append(f"{path.relative_to(ROOT)}:{number} {name}")
    assert not found, "\n".join(found)


def test_qss_has_no_literal_colors():
    text = (ROOT / "ui" / "theme_qss.py").read_text(encoding="utf-8")
    assert not FORBIDDEN["color hexadecimal"].search(text)


def test_theme_resolution():
    assert resolve_theme("light") is LIGHT
    assert resolve_theme("dark") is DARK
    assert resolve_theme("system") is LIGHT  # el viejo "como el escritorio"
    assert [next_theme("light"), next_theme("dark"), next_theme("system")] == [
        "dark",
        "light",
        "dark",
    ]
