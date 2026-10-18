"""Hoja de estilo de la aplicacion: se arma con los tokens de ``ui/theme.py``.

Aqui no hay colores propios: cada regla toma el suyo de ``ColorTokens``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.theme import ColorTokens

RADIUS = 5
PILL_RADIUS = 11  # extremos de los botones segmentados
PANEL_RADIUS = 10


def build_qss(colors: ColorTokens) -> str:
    c = colors
    return f"""
QPushButton, QToolButton {{
    background: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS}px;
    padding: 5px 12px;
}}
QToolButton {{ padding: 4px; }}
QPushButton:hover, QToolButton:hover {{ background: {c.surface_alt}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {c.brand_soft}; }}
QPushButton:focus, QToolButton:focus {{ border-color: {c.brand}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {c.text_muted}; border-color: {c.border_soft}; }}
QPushButton[role="primary"] {{
    background: {c.brand};
    color: {c.on_brand};
    border-color: {c.brand};
    font-weight: 600;
    padding: 6px 18px;
}}
QPushButton[role="primary"]:disabled {{
    background: {c.brand_soft};
    color: {c.text_muted};
    border-color: {c.brand_soft};
}}
QPushButton[role="danger"] {{
    color: {c.error};
    border-color: {c.error};
    background: transparent;
    font-weight: 600;
    padding: 6px 18px;
}}
QPushButton[role="danger"]:hover {{ background: {c.surface_alt}; }}
QPushButton[role="quiet"] {{ color: {c.text_muted}; border-color: transparent; background: transparent; }}
QPushButton[role="quiet"]:hover {{ color: {c.text}; background: {c.surface_alt}; }}
QLineEdit, QPlainTextEdit {{
    background: {c.surface};
    border: 1px solid {c.border};
    border-radius: {RADIUS}px;
    padding: 4px 6px;
    selection-background-color: {c.brand};
    selection-color: {c.on_brand};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {c.brand}; }}
QToolTip {{
    background: {c.text};
    color: {c.surface};
    border: none;
    padding: 4px 6px;
}}
QProgressBar {{
    border: none;
    border-radius: 3px;
    background: {c.border_soft};
    max-height: 6px;
    min-height: 6px;
}}
QProgressBar::chunk {{ border-radius: 3px; background: {c.brand}; }}
QLabel[tone="ok"] {{ color: {c.ok}; }}
QLabel[tone="warning"] {{ color: {c.warning}; }}
QLabel[tone="error"] {{ color: {c.error}; }}
QLabel[tone="info"] {{ color: {c.brand}; }}
QLabel[tone="muted"] {{ color: {c.text_muted}; }}
QLabel[kind="title"] {{ font-weight: 600; }}
QFrame[kind="sidebar"] {{ background: {c.sidebar}; border: none; }}
QFrame[kind="sidebar"] QPushButton {{
    text-align: left;
    padding: 0 9px;
    background: transparent;
    color: {c.sidebar_text};
    border: none;
    border-radius: 8px;
}}
QFrame[kind="sidebar"] QPushButton:hover {{ background: {c.sidebar_active}; }}
QFrame[kind="sidebar"] QPushButton:checked {{
    background: {c.sidebar_active};
    color: {c.sidebar_ink};
    font-weight: 600;
}}
QFrame[kind="rule"] {{
    background: {c.border_soft};
    border: none;
    min-height: 1px;
    max-height: 1px;
}}
QFrame[kind="panel"] {{
    background: {c.surface};
    border: 1px solid {c.border};
    border-radius: {PANEL_RADIUS}px;
}}
QFrame[kind="drop"] {{
    background: {c.surface};
    border: 2px dashed {c.border};
    border-radius: {PANEL_RADIUS}px;
}}
QFrame[kind="drop"]:hover {{ border-color: {c.text_muted}; }}
QFrame[kind="drop"][drag="on"] {{ border-color: {c.brand}; background: {c.brand_soft}; }}
QFrame[kind="drop"] QLabel {{ background: transparent; border: none; }}
QScrollArea[kind="chat"] {{ background: transparent; border: 1px solid transparent; border-radius: {PANEL_RADIUS}px; }}
QScrollArea[kind="chat"] > QWidget > QWidget {{ background: transparent; }}
QScrollArea[kind="chat"][drag="on"] {{ border-color: {c.brand}; background: {c.brand_soft}; }}
QScrollArea[kind="chat"] QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollArea[kind="chat"] QScrollBar::handle:vertical {{
    background: {c.border};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollArea[kind="chat"] QScrollBar::handle:vertical:hover {{ background: {c.text_muted}; }}
QScrollArea[kind="chat"] QScrollBar::add-line:vertical, QScrollArea[kind="chat"] QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollArea[kind="chat"] QScrollBar::add-page:vertical, QScrollArea[kind="chat"] QScrollBar::sub-page:vertical {{ background: transparent; }}
QFrame[kind="bubble_in"] {{
    background: {c.surface};
    border: 1px solid {c.border};
    border-radius: {PANEL_RADIUS}px;
}}
QFrame[kind="bubble_out"] {{
    background: {c.brand_soft};
    border: 1px solid {c.border};
    border-radius: {PANEL_RADIUS}px;
}}
QFrame[kind="bubble_in"] QLabel, QFrame[kind="bubble_out"] QLabel {{ background: transparent; border: none; }}
QPushButton[kind="segment"] {{
    border: 1px solid {c.border};
    border-left: none;
    border-radius: 0;
    padding: 4px 14px;
    background: {c.surface_alt};
}}
QPushButton[kind="segment"]:hover {{ background: {c.border_soft}; }}
QPushButton[kind="segment"]:checked {{ background: {c.brand}; color: {c.on_brand}; }}
QPushButton[kind="segment"]:disabled {{ color: {c.text_muted}; }}
QPushButton[kind="segment"]:checked:disabled {{ background: {c.brand_soft}; color: {c.text_muted}; }}
QPushButton[kind="segment"]#first {{
    border-left: 1px solid {c.border};
    border-top-left-radius: {PILL_RADIUS}px;
    border-bottom-left-radius: {PILL_RADIUS}px;
}}
QPushButton[kind="segment"]#last {{
    border-top-right-radius: {PILL_RADIUS}px;
    border-bottom-right-radius: {PILL_RADIUS}px;
}}
""".strip()
