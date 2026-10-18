"""Tema central de la interfaz: color, espacios y letra.

Es el unico lugar con colores. Sigue la direccion "Descifrado": hueso, papel,
grafito y tinta, con la barra lateral oscura y el sello ocre del logo. Genera
la ``QPalette`` y aplica la hoja de estilo
(``ui/theme_qss.py``, que solo lee estos tokens). Los modulos piden un rol de
boton (``set_role``), un tono (``set_tone``) o una pieza (``set_kind``); nunca un
color ni ``setStyleSheet`` (lo vigila ``tests/test_00_ui_theme_guard.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from ui.theme_qss import build_qss

STYLE_NAME = "Fusion"
ROLE_PROPERTY = "role"
TONE_PROPERTY = "tone"
KIND_PROPERTY = "kind"
DRAG_PROPERTY = "drag"


@dataclass(frozen=True)
class ColorTokens:
    """Colores con nombre de uso, no de tono."""

    background: str  # hueso: fondo de la ventana
    surface: str  # papel: campos y paneles
    surface_alt: str  # segmentos sin elegir, hover
    border: str
    border_soft: str
    text: str  # grafito
    text_muted: str
    brand: str  # tinta: primario, seleccion, enlaces
    brand_soft: str  # velo de tinta: zona de soltar activa
    on_brand: str
    sidebar: str
    sidebar_text: str
    sidebar_active: str
    sidebar_ink: str  # boton activo de la barra y el trazo del logo sobre ella
    shadow: str  # #AARRGGBB: la sombra de la barra lateral desplegada
    seal: str  # ocre: solo el logo
    ok: str
    warning: str
    error: str


LIGHT = ColorTokens(
    background="#ECE8DF",
    surface="#FBF9F4",
    surface_alt="#F3F0E8",
    border="#D8D2C4",
    border_soft="#E6E1D5",
    text="#1E2427",
    text_muted="#5F686C",
    brand="#1F5266",
    brand_soft="#DCE6E8",
    on_brand="#FFFFFF",
    sidebar="#173540",
    sidebar_text="#B9CBD0",
    sidebar_active="#24505F",
    sidebar_ink="#FBF9F4",
    shadow="#50000000",
    seal="#A8802F",
    ok="#2E7550",
    warning="#A65A0C",
    error="#AE3329",
)

# Tinta nocturna: el mismo tono frio, la barra mas oscura que el fondo.
DARK = ColorTokens(
    background="#12191C",
    surface="#182226",
    surface_alt="#1E2A2F",
    border="#34444A",
    border_soft="#26343A",
    text="#E6E2D8",
    text_muted="#9AA6A9",
    brand="#7DBCD0",
    brand_soft="#23414B",
    on_brand="#0F1E24",
    sidebar="#0C1417",
    sidebar_text="#9DB4BA",
    sidebar_active="#1C3640",
    sidebar_ink="#F3EFE6",
    shadow="#80000000",
    seal="#C9A04A",
    ok="#6CC495",
    warning="#E0A15A",
    error="#F0857A",
)

THEMES: dict[str, ColorTokens] = {"light": LIGHT, "dark": DARK}
# El orden del boton de tema en la barra lateral.
THEME_CYCLE = ("light", "dark")


def resolve_theme(name: str) -> ColorTokens:
    """Los tokens del tema ``name``; uno desconocido es el claro."""
    return THEMES.get(name, LIGHT)


def next_theme(name: str) -> str:
    index = THEME_CYCLE.index(name) if name in THEME_CYCLE else 0
    return THEME_CYCLE[(index + 1) % len(THEME_CYCLE)]


@dataclass(frozen=True)
class Density:
    margin: int
    spacing: int


SPACING_SCALE = (4, 8, 12, 16, 24)
WIDE = Density(margin=16, spacing=10)


@dataclass(frozen=True)
class ThemeFonts:
    """Familias ya cargadas en Qt; vacias si no se pudieron cargar (queda la del sistema)."""

    sans: str = ""
    mono: str = ""


class ButtonRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    DANGER = "danger"
    QUIET = "quiet"


class Tone(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"
    MUTED = "muted"


class Kind(StrEnum):
    """Piezas compuestas que la hoja de estilo pinta enteras."""

    SIDEBAR = "sidebar"  # la barra lateral oscura y sus botones
    SEGMENT = "segment"  # un boton de una pieza segmentada
    PANEL = "panel"  # ficha con borde y fondo de papel
    DROP = "drop"  # zona para soltar el video
    RULE = "rule"  # linea horizontal de 1 px
    TITLE = "title"  # texto grande en negrita
    CHAT = "chat"  # la conversacion: se ilumina al soltar archivos
    BUBBLE_IN = "bubble_in"  # burbuja de lo que llega
    BUBBLE_OUT = "bubble_out"  # burbuja de lo que sale


_current: dict[str, object] = {"tokens": LIGHT, "fonts": ThemeFonts()}


def tokens() -> ColorTokens:
    """Los colores del tema aplicado."""
    return _current["tokens"]  # type: ignore[return-value]


def tone_color(tone: Tone, colors: ColorTokens | None = None) -> QColor:
    colors = colors or tokens()
    by_tone = {
        Tone.OK: colors.ok,
        Tone.WARNING: colors.warning,
        Tone.ERROR: colors.error,
        Tone.INFO: colors.brand,
        Tone.MUTED: colors.text_muted,
    }
    return QColor(by_tone[tone])


def mono_font(base: QFont | None = None) -> QFont:
    """La letra de cifras y rutas, del tamano de ``base`` (o el de la app)."""
    font = QFont(base) if base is not None else QApplication.font()
    family = _current["fonts"].mono  # type: ignore[union-attr]
    if family:
        font.setFamily(family)
    else:
        font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def _set_property(widget: QWidget, name: str, value: str) -> None:
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def set_role(widget: QWidget, role: ButtonRole) -> None:
    _set_property(widget, ROLE_PROPERTY, role.value)


def set_tone(widget: QWidget, tone: Tone | None) -> None:
    _set_property(widget, TONE_PROPERTY, tone.value if tone else "")


def set_kind(widget: QWidget, kind: Kind) -> None:
    _set_property(widget, KIND_PROPERTY, kind.value)


def set_drag_active(widget: QWidget, active: bool) -> None:
    """Resalta la zona de soltar mientras un archivo pasa por encima."""
    _set_property(widget, DRAG_PROPERTY, "on" if active else "")


def role_text_color(role: ButtonRole) -> QColor:
    colors = tokens()
    by_role = {
        ButtonRole.PRIMARY: colors.on_brand,
        ButtonRole.SECONDARY: colors.text,
        ButtonRole.DANGER: colors.error,
        ButtonRole.QUIET: colors.text_muted,
    }
    return QColor(by_role[role])


def seal_colors(on_dark: bool = False) -> tuple[QColor, QColor]:
    """Tinta del trazo y ocre del sello; sobre la barra lateral el trazo va claro."""
    colors = tokens()
    ink = colors.sidebar_ink if on_dark else colors.brand
    return QColor(ink), QColor(colors.seal)


def shadow_color() -> QColor:
    return QColor(tokens().shadow)


def sidebar_palette(base: QPalette) -> QPalette:
    """La paleta de la barra oscura: los iconos toman sus colores de aqui."""
    colors = tokens()
    palette = QPalette(base)
    palette.setColor(QPalette.ColorRole.Window, QColor(colors.sidebar))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors.sidebar_text))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors.sidebar_text))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors.sidebar_ink))
    return palette


def build_palette(colors: ColorTokens) -> QPalette:
    """La ``QPalette`` de la app: la usan los widgets que la hoja de estilo no toca."""
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: colors.background,
        QPalette.ColorRole.WindowText: colors.text,
        QPalette.ColorRole.Base: colors.surface,
        QPalette.ColorRole.AlternateBase: colors.surface_alt,
        QPalette.ColorRole.Text: colors.text,
        QPalette.ColorRole.PlaceholderText: colors.text_muted,
        QPalette.ColorRole.Button: colors.surface,
        QPalette.ColorRole.ButtonText: colors.text,
        QPalette.ColorRole.Highlight: colors.brand,
        QPalette.ColorRole.HighlightedText: colors.on_brand,
        QPalette.ColorRole.ToolTipBase: colors.text,
        QPalette.ColorRole.ToolTipText: colors.surface,
        QPalette.ColorRole.Link: colors.brand,
        QPalette.ColorRole.Mid: colors.border,
        QPalette.ColorRole.Midlight: colors.border_soft,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    disabled = QPalette.ColorGroup.Disabled
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(disabled, role, QColor(colors.text_muted))
    return palette


def apply_theme(app: QApplication, fonts: ThemeFonts, colors: ColorTokens = LIGHT) -> None:
    """Fusion, paleta, letra y hoja de estilo; se llama al arrancar y al cambiar de tema."""
    _current["tokens"] = colors
    _current["fonts"] = fonts
    app.setStyle(STYLE_NAME)
    app.setPalette(build_palette(colors))
    if fonts.sans:
        # Solo la familia: el tamano del sistema se respeta.
        font = app.font()
        font.setFamily(fonts.sans)
        app.setFont(font)
    app.setStyleSheet(build_qss(colors))
