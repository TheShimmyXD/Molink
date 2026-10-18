from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules.mod_02_pair.logic._02_logic_pair import PeerRow, Status
from modules.mod_02_pair.logic._02_logic_pair import Tone as StatusTone
from ui.blocks.icons import GlyphLabel
from ui.theme import ButtonRole, Kind, Tone, mono_font, set_kind, set_role, set_tone

CODE_FIELD_WIDTH = 172
CODE_POINT_SIZE = 20
STATUS_TONES = {StatusTone.NEUTRAL: Tone.INFO, StatusTone.OK: Tone.OK, StatusTone.ERROR: Tone.ERROR}


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    set_tone(label, Tone.MUTED)
    return label


def _mono(text: str = "", size: int = 0, bold: bool = False) -> QLabel:
    label = QLabel(text)
    font = mono_font()
    if size:
        font.setPointSize(size)
    font.setBold(bold)
    label.setFont(font)
    return label


def _button(text: str, role: ButtonRole) -> QPushButton:
    button = QPushButton(text)
    set_role(button, role)
    return button


def _rule() -> QFrame:
    line = QFrame()
    set_kind(line, Kind.RULE)
    line.setFixedHeight(1)
    return line


def _status_glyph(status: Status) -> tuple[str, Tone]:
    if status.tone is StatusTone.ERROR:
        return "warning-circle", Tone.ERROR
    if status.tone is StatusTone.OK:
        return "check-circle", Tone.OK
    return ("broadcast" if status.busy else "link"), Tone.INFO


class PeerRowWidget(QWidget):
    """Una fila: equipo, IP y, segun el caso, el codigo + Emparejar u Olvidar."""

    def __init__(self, name: str, coordinator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self._coordinator = coordinator
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 4, 0, 4)
        col.setSpacing(2)
        line = QHBoxLayout()
        line.setSpacing(8)
        line.addWidget(GlyphLabel("desktop", 20))
        title = QLabel(name)
        font = QFont(title.font())
        font.setBold(True)
        title.setFont(font)
        line.addWidget(title)
        self.address = _mono()
        line.addWidget(self.address)
        self.paired_icon = GlyphLabel("check-circle", 16, Tone.OK)
        self.paired_text = _muted("emparejado")
        line.addWidget(self.paired_icon)
        line.addWidget(self.paired_text)
        line.addStretch(1)

        self.code = QLineEdit()
        self.code.setPlaceholderText("Código de allá")
        self.code.setToolTip("Los 6 dígitos que muestra ese equipo en 'Mi código'")
        self.code.setFont(mono_font())
        self.code.setMaxLength(7)
        self.code.setFixedWidth(CODE_FIELD_WIDTH)
        self.code.returnPressed.connect(self._join)
        self.join_button = _button("Emparejar", ButtonRole.PRIMARY)
        self.join_button.clicked.connect(self._join)
        self.forget_button = _button("Olvidar", ButtonRole.QUIET)
        self.forget_button.setToolTip("Quita el emparejamiento: ese equipo ya no podrá entrar")
        self.forget_button.clicked.connect(lambda: self._coordinator.forget(self.name))
        for widget in (self.code, self.join_button, self.forget_button):
            line.addWidget(widget)
        col.addLayout(line)

        self.error = QLabel()
        self.error.setWordWrap(True)
        set_tone(self.error, Tone.ERROR)
        col.addWidget(self.error)

    def update_row(self, row: PeerRow, online: bool) -> None:
        self.address.setText(row.address or "no está en la red")
        set_tone(self.address, None if row.address else Tone.MUTED)
        self.paired_icon.setVisible(row.paired)
        self.paired_text.setVisible(row.paired)
        self.forget_button.setVisible(row.paired)
        self.code.setVisible(not row.paired)
        self.join_button.setVisible(not row.paired)
        self.join_button.setText("Emparejando..." if row.joining else "Emparejar")
        self.join_button.setEnabled(online and not row.joining)
        self.code.setEnabled(online and not row.joining)
        if row.paired:
            self.code.clear()
        self.error.setText(row.error)
        self.error.setVisible(bool(row.error))

    def _join(self) -> None:
        if self.join_button.isEnabled():
            self._coordinator.join(self.name, self.code.text())


class PairWidget(QWidget):
    """
    Pantalla de emparejar en una columna: arriba el estado, en medio los
    equipos y abajo la franja de 'Mi codigo'.

    Solo habla con el coordinador; lo pinta todo desde su vista.
    """

    def __init__(self, coordinator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.coordinator = coordinator
        self._rows: dict[str, PeerRowWidget] = {}
        self._build_ui()
        coordinator.view_changed.connect(self.render)
        self.render(coordinator.view())
        coordinator.start()

    def _build_ui(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(8)

        status = QHBoxLayout()
        status.setSpacing(8)
        self.status_icon = GlyphLabel("broadcast", 16, Tone.INFO)
        self.status_text = QLabel()
        self.status_text.setWordWrap(True)
        status.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)
        status.addWidget(self.status_text, 1)
        col.addLayout(status)
        col.addWidget(_rule())

        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        self.list_layout = QVBoxLayout(holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(2)
        self.list_layout.addStretch(1)
        self.list_area.setWidget(holder)
        col.addWidget(self.list_area, 1)
        col.addWidget(_rule())

        mine = QHBoxLayout()
        mine.setContentsMargins(0, 4, 0, 0)
        mine.setSpacing(10)
        self.mine_label = _muted("Mi código")
        self.code_label = _mono("", CODE_POINT_SIZE, True)
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.countdown = _muted()
        self.show_button = _button("Mostrar mi código", ButtonRole.SECONDARY)
        self.show_button.setToolTip(
            "Abre 2 minutos la puerta de emparejar para que el otro equipo escriba este código"
        )
        self.show_button.clicked.connect(self.coordinator.open_window)
        self.close_button = _button("Cerrar", ButtonRole.DANGER)
        self.close_button.setToolTip("Cierra la puerta de emparejar ahora")
        self.close_button.clicked.connect(self.coordinator.close_window)
        for widget in (self.mine_label, self.code_label, self.countdown):
            mine.addWidget(widget)
        mine.addStretch(1)
        mine.addWidget(self.show_button)
        mine.addWidget(self.close_button)
        col.addLayout(mine)

    # -- Pintar la vista ---------------------------------------

    def render(self, view: dict) -> None:
        online = view["state"] == "ONLINE"
        status: Status = view["status"]
        glyph, tone = _status_glyph(status)
        self.status_icon.set_glyph(glyph, tone)
        self.status_text.setText(status.text + (f"\n{status.hint}" if status.hint else ""))
        set_tone(self.status_text, Tone.ERROR if status.tone is StatusTone.ERROR else None)
        self._render_rows(view["rows"], online)
        self._render_window(view, online)

    def _render_rows(self, rows: list[PeerRow], online: bool) -> None:
        names = [row.name for row in rows]
        for name in list(self._rows):
            if name not in names:
                widget = self._rows.pop(name)
                self.list_layout.removeWidget(widget)
                widget.deleteLater()
        for index, row in enumerate(rows):
            widget = self._rows.get(row.name)
            if widget is None:
                widget = self._rows[row.name] = PeerRowWidget(row.name, self.coordinator)
            self.list_layout.insertWidget(index, widget)
            widget.update_row(row, online)

    def _render_window(self, view: dict, online: bool) -> None:
        is_open = view["window_open"]
        code = view["code"]
        self.mine_label.setVisible(is_open)
        self.code_label.setVisible(is_open)
        self.countdown.setVisible(is_open)
        self.close_button.setVisible(is_open)
        self.show_button.setVisible(not is_open)
        self.show_button.setEnabled(online)
        self.code_label.setText(f"{code[:3]} {code[3:]}" if is_open else "")
        minutes, seconds = divmod(view["remaining"], 60)
        self.countdown.setText(f"vence en {minutes}:{seconds:02d}")

    def closeEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        self.coordinator.close()
        super().closeEvent(event)
