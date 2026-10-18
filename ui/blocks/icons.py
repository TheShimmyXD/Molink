"""Iconos de Phosphor (MIT) dibujados con su fuente en el color del tema.

La ventana principal carga la fuente y su mapa ``nombre -> codigo``
(``managers/icon_font.py``) y los entrega con ``set_icon_font``. Los botones y
etiquetas con icono (``GlyphButton``, ``GlyphLabel``) lo vuelven a pintar
cuando cambia la paleta: asi el cambio de tema no deja iconos del color viejo.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QLabel, QToolButton, QWidget

from ui.theme import Tone, tone_color

logger = logging.getLogger(__name__)

# Dibujo a doble resolucion: nitido en pantallas con escala.
PIXEL_RATIO = 2.0
DOT_RATIO = 0.18  # radio del punto de pendiente, en fraccion del icono
REPAINT_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.StyleChange)

_font: dict[str, object] = {"family": "", "codes": {}}


def set_icon_font(family: str, codes: dict[str, str]) -> None:
    """La familia ya cargada en Qt y su mapa; sin llamarla, los iconos salen vacios."""
    _font["family"] = family
    _font["codes"] = codes


def glyph_pixmap(name: str, color: QColor, size: int, dot: QColor | None = None) -> QPixmap:
    """El icono ``name`` de ``size`` px; sin fuente o con un nombre que no existe, vacio.

    Con ``dot`` lleva un punto de ese color arriba a la derecha (algo pendiente).
    """
    pixmap = QPixmap(int(size * PIXEL_RATIO), int(size * PIXEL_RATIO))
    pixmap.setDevicePixelRatio(PIXEL_RATIO)
    pixmap.fill(Qt.GlobalColor.transparent)
    family, codes = _font["family"], _font["codes"]
    code = codes.get(name)  # type: ignore[union-attr]
    if not code:
        if family:
            logger.warning("No hay un icono %r en Phosphor", name)
        return pixmap
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont(family)  # type: ignore[arg-type]
    font.setPixelSize(size)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, chr(int(code, 16)))
    if dot is not None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        radius = size * DOT_RATIO
        painter.drawEllipse(QRectF(size - 2 * radius, 0, 2 * radius, 2 * radius))
    painter.end()
    return pixmap


def glyph_icon(name: str, palette: QPalette, size: int, dot: QColor | None = None) -> QIcon:
    """Icono para un boton: color del texto y, marcado, el del texto seleccionado."""
    icon = QIcon()
    normal = palette.color(QPalette.ColorRole.ButtonText)
    selected = palette.color(QPalette.ColorRole.HighlightedText)
    disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    icon.addPixmap(glyph_pixmap(name, normal, size, dot), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(glyph_pixmap(name, selected, size, dot), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(glyph_pixmap(name, disabled, size, dot), QIcon.Mode.Disabled, QIcon.State.Off)
    return icon


class GlyphButton(QToolButton):
    """Boton de solo icono; la explicacion va en la ayuda (tooltip)."""

    def __init__(self, glyph: str, tip: str, size: int = 18, parent: QWidget | None = None):
        super().__init__(parent)
        self._glyph = glyph
        self._size = size
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setIconSize(QSize(size, size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._repaint()

    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self._repaint()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (nombre impuesto por Qt)
        super().changeEvent(event)
        if event.type() in REPAINT_EVENTS:
            self._repaint()

    def _repaint(self) -> None:
        self.setIcon(glyph_icon(self._glyph, self.palette(), self._size))


class GlyphLabel(QLabel):
    """Icono suelto en el color de un tono (o en el del texto, sin tono)."""

    def __init__(self, glyph: str, size: int, tone: Tone | None = None, parent=None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._size = size
        self._tone = tone
        self.setFixedSize(size, size)
        self._repaint()

    def set_glyph(self, glyph: str, tone: Tone | None = None) -> None:
        self._glyph = glyph
        self._tone = tone
        self._repaint()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (nombre impuesto por Qt)
        super().changeEvent(event)
        if event.type() in REPAINT_EVENTS:
            self._repaint()

    def _repaint(self) -> None:
        if self._tone is None:
            color = self.palette().color(QPalette.ColorRole.WindowText)
        else:
            color = tone_color(self._tone)
        self.setPixmap(glyph_pixmap(self._glyph, color, self._size))
