"""El logo de Molink: un sello ocre perforado con dos equipos enlazados.

Se dibuja con QPainter sobre una rejilla de 64, en cualquier tamano y con los
colores del tema; no hay archivo de imagen. Dentro del sello,
dos nodos de tinta unidos por un trazo: la laptop y la sobremesa.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from ui.theme import seal_colors

GRID = 64.0
CENTER = QPointF(32, 32)
OUTER_RADIUS, OUTER_WIDTH = 29.0, 3.0
INNER_RADIUS, INNER_WIDTH = 23.5, 2.0
# Trazo de 2.2 y hueco de 3.4 en la rejilla; Qt los mide en anchos de linea.
INNER_DASHES = (2.2 / INNER_WIDTH, 3.4 / INNER_WIDTH)
# Los dos nodos (centro x, radio) y el enlace entre ellos, sobre la rejilla.
NODES = ((20.0, 6.0), (44.0, 6.0))
LINK_WIDTH = 3.6
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
PIXEL_RATIO = 2.0


def paint_seal(painter: QPainter, rect: QRectF, ink: QColor, seal: QColor) -> None:
    """Dibuja el sello dentro de ``rect`` (cuadrado)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.topLeft())
    scale = min(rect.width(), rect.height()) / GRID
    painter.scale(scale, scale)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    painter.setPen(QPen(seal, OUTER_WIDTH))
    painter.drawEllipse(CENTER, OUTER_RADIUS, OUTER_RADIUS)
    dashed = QPen(seal, INNER_WIDTH)
    dashed.setDashPattern(list(INNER_DASHES))
    painter.setPen(dashed)
    painter.drawEllipse(CENTER, INNER_RADIUS, INNER_RADIUS)

    painter.setPen(QPen(ink, LINK_WIDTH))
    (left, left_r), (right, right_r) = NODES
    painter.drawLine(QPointF(left + left_r, CENTER.y()), QPointF(right - right_r, CENTER.y()))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ink)
    for x, radius in NODES:
        painter.drawEllipse(QPointF(x, CENTER.y()), radius, radius)
    painter.restore()


def seal_pixmap(size: int, on_dark: bool = False, pixel_ratio: float = PIXEL_RATIO) -> QPixmap:
    """El logo de ``size`` px; ``on_dark`` para la barra lateral oscura."""
    pixmap = QPixmap(int(size * pixel_ratio), int(size * pixel_ratio))
    pixmap.setDevicePixelRatio(pixel_ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_seal(painter, QRectF(0, 0, size, size), *seal_colors(on_dark))
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """Icono de la ventana en todos los tamanos, a resolucion 1."""
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(seal_pixmap(size, pixel_ratio=1.0))
    return icon
