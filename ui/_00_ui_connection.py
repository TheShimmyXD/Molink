"""Linea de estado de la conexion al pie del area de trabajo.

Punto de color y texto a la izquierda; a la derecha la IP y el puerto de este
equipo o, tras un error, 'Reintentar ahora'. Pinta un ConnectionLine; no
sabe nada de la red.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from logic._00_logic_connection import ConnectionLine
from logic._00_logic_targets import Tone as LineTone
from ui.theme import ButtonRole, Kind, Tone, mono_font, set_kind, set_role, set_tone, tone_color

DOT_SIZE = 9
LINE_TONES = {
    LineTone.NEUTRAL: Tone.MUTED,
    LineTone.OK: Tone.OK,
    LineTone.WARNING: Tone.WARNING,
    LineTone.ERROR: Tone.ERROR,
}
ADDRESS_TIP = "IP y puerto de este equipo en la red local"


class ConnectionBar(QWidget):
    """``retry_requested`` al pulsar 'Reintentar ahora'."""

    retry_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tone = Tone.MUTED
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        rule = QFrame()
        set_kind(rule, Kind.RULE)
        rule.setFixedHeight(1)
        col.addWidget(rule)

        row = QHBoxLayout()
        row.setContentsMargins(16, 3, 10, 3)
        row.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(DOT_SIZE, DOT_SIZE)
        self.text = QLabel()
        self.address = QLabel()
        self.address.setFont(mono_font())
        self.address.setToolTip(ADDRESS_TIP)
        set_tone(self.address, Tone.MUTED)
        self.retry_button = QPushButton("Reintentar ahora")
        set_role(self.retry_button, ButtonRole.QUIET)
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.clicked.connect(self.retry_requested)
        row.addWidget(self.dot)
        row.addWidget(self.text, 1)
        row.addWidget(self.address)
        row.addWidget(self.retry_button)
        col.addLayout(row)
        self.show_line(ConnectionLine("", LineTone.NEUTRAL))

    def show_line(self, line: ConnectionLine) -> None:
        self._tone = LINE_TONES[line.tone]
        self._paint_dot()
        self.text.setText(line.text)
        self.text.setToolTip(line.hint)
        # El texto en su color solo si pide atencion; si no, apagado como el resto del pie.
        set_tone(self.text, self._tone if line.tone is LineTone.ERROR else Tone.MUTED)
        self.address.setText(line.address)
        self.address.setVisible(bool(line.address) and not line.can_retry)
        self.retry_button.setVisible(line.can_retry)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (nombre impuesto por Qt)
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_dot()  # tema claro u oscuro

    def _paint_dot(self) -> None:
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(int(DOT_SIZE * ratio), int(DOT_SIZE * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tone_color(self._tone))
        painter.drawEllipse(0, 0, DOT_SIZE, DOT_SIZE)
        painter.end()
        self.dot.setPixmap(pixmap)
