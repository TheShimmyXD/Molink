from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.mod_03_console.logic._03_logic_console import Outcome
from modules.mod_03_console.logic._03_logic_console import Tone as OutcomeTone
from ui.blocks.icons import GlyphLabel
from ui.theme import ButtonRole, Kind, Tone, mono_font, set_kind, set_role, set_tone

MAX_LINES = 5_000  # lo mas viejo de la salida se descarta
TARGET_WIDTH = 160
PROMPT_WIDTH = 180  # la carpeta larga se corta por la izquierda
OUTCOME_TONES = {
    OutcomeTone.NEUTRAL: Tone.MUTED,
    OutcomeTone.OK: Tone.OK,
    OutcomeTone.WARNING: Tone.WARNING,
    OutcomeTone.ERROR: Tone.ERROR,
}


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    set_tone(label, Tone.MUTED)
    return label


def _mono(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setFont(mono_font())
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


class ConsoleWidget(QWidget):
    """
    Consola en una columna: arriba el equipo, en medio la salida y
    abajo el comando con Correr, que mientras corre pasa a Cancelar.

    La linea muestra la carpeta del otro equipo y recorre lo ya corrido con
    las flechas. Si el comando lleva sudo, la linea pasa a pedir la
    contrasena en un campo oculto; al enviarla el campo se vacia.

    Solo habla con el coordinador; pinta el estado desde su vista y anade la
    salida que le llega por output_added.
    """

    def __init__(self, coordinator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.coordinator = coordinator
        self._running = False
        self._asking = False
        self._can_run = False
        self._build_ui()
        coordinator.view_changed.connect(self.render)
        coordinator.output_added.connect(self.append_output)
        coordinator.output_cleared.connect(self.output.clear)
        self.render(coordinator.view())
        coordinator.start()

    def _build_ui(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.status_icon = GlyphLabel("terminal-window", 16, Tone.INFO)
        self.on_label = _muted("En")
        self.target = QComboBox()
        self.target.setMinimumWidth(TARGET_WIDTH)
        self.target.setToolTip("Equipo emparejado donde corre el comando")
        self.target.currentTextChanged.connect(self._choose)
        self.address = _mono()
        set_tone(self.address, Tone.MUTED)
        self.status_text = QLabel()
        self.status_text.setWordWrap(True)
        top.addWidget(self.status_icon)
        top.addWidget(self.on_label)
        top.addWidget(self.target)
        top.addWidget(self.address)
        top.addWidget(self.status_text, 1)
        top.addStretch(0)
        col.addLayout(top)
        col.addWidget(_rule())

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(mono_font())
        self.output.setMaximumBlockCount(MAX_LINES)
        self.output.setPlaceholderText("Aquí sale lo que escribe el comando.")
        col.addWidget(self.output, 1)
        col.addWidget(_rule())

        line = QHBoxLayout()
        line.setSpacing(8)
        self.prompt = _mono("~ $")
        self.prompt.setToolTip("Carpeta del otro equipo donde corre el comando")
        self.lock_icon = GlyphLabel("lock", 16, Tone.WARNING)
        self.command = QLineEdit()
        self.command.setFont(mono_font())
        self.command.setPlaceholderText("Comando, por ejemplo hostname")
        self.command.setToolTip(
            "Corre en el otro equipo sin terminal: si pide teclado, recibe fin de entrada."
            " Las flechas arriba y abajo recorren lo ya corrido; clear o Ctrl+L limpian."
        )
        self.command.textChanged.connect(self._update_buttons)
        self.command.returnPressed.connect(self._run)
        self.command.installEventFilter(self)
        self.password = QLineEdit()
        self.password.setFont(mono_font())
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setToolTip("Viaja cifrada al otro equipo; no se guarda ni va al log")
        self.password.returnPressed.connect(self._send_password)
        self.run_button = _button("Correr", ButtonRole.PRIMARY)
        self.run_button.clicked.connect(self._run)
        self.send_button = _button("Enviar", ButtonRole.PRIMARY)
        self.send_button.clicked.connect(self._send_password)
        self.cancel_button = _button("Cancelar", ButtonRole.DANGER)
        self.cancel_button.setToolTip("Termina el comando en el otro equipo")
        self.cancel_button.clicked.connect(self.coordinator.cancel)
        line.addWidget(self.prompt)
        line.addWidget(self.lock_icon)
        line.addWidget(self.command, 1)
        line.addWidget(self.password, 1)
        line.addWidget(self.run_button)
        line.addWidget(self.send_button)
        line.addWidget(self.cancel_button)
        col.addLayout(line)

        self.outcome = QLabel()
        self.outcome.setWordWrap(True)
        col.addWidget(self.outcome)

    # -- Pintar la vista ---------------------------------------

    def render(self, view: dict) -> None:
        self._running = view["running"]
        was_asking, self._asking = self._asking, view["asking"]
        self._can_run = view["state"] == "READY"
        self._render_target(view)
        self._render_line(view, was_asking)
        self._render_outcome(view["outcome"])
        if self._asking:
            self.outcome.setVisible(True)
            self.outcome.setText(f"sudo pide la contraseña de {view['target']}. No se guarda.")
            set_tone(self.outcome, Tone.WARNING)
        self._update_buttons()

    def append_output(self, text: str) -> None:
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def _render_target(self, view: dict) -> None:
        status: Outcome | None = view["status"]
        has_target = status is None
        for widget in (self.on_label, self.target, self.address):
            widget.setVisible(has_target)
        self.status_text.setVisible(not has_target)
        self.status_icon.set_glyph("terminal-window" if has_target else "plugs", Tone.INFO)
        if not has_target:
            self.status_text.setText(f"{status.text}\n{status.hint}")
        names = [name for name, _ in view["targets"]]
        if names != [self.target.itemText(i) for i in range(self.target.count())]:
            self.target.blockSignals(True)
            self.target.clear()
            self.target.addItems(names)
            self.target.blockSignals(False)
        self.target.setCurrentText(view["target"])
        self.target.setEnabled(not (self._running or self._asking))
        self.address.setText(view["address"])

    def _render_outcome(self, outcome: Outcome | None) -> None:
        self.outcome.setVisible(outcome is not None)
        if outcome is None:
            return
        self.outcome.setText(outcome.text + (f" {outcome.hint}" if outcome.hint else ""))
        set_tone(self.outcome, OUTCOME_TONES[outcome.tone])

    def _render_line(self, view: dict, was_asking: bool) -> None:
        metrics = self.prompt.fontMetrics()
        text = metrics.elidedText(f"{view['prompt']} $", Qt.TextElideMode.ElideLeft, PROMPT_WIDTH)
        self.prompt.setText(text)
        self.prompt.setVisible(not self._asking)
        self.command.setVisible(not self._asking)
        self.lock_icon.setVisible(self._asking)
        self.password.setVisible(self._asking)
        if self._asking and not was_asking:
            self.password.setPlaceholderText(f"Contraseña de sudo en {view['target']}")
            self.password.setFocus()
        elif was_asking and not self._asking:
            self.password.clear()
            self.command.setFocus()

    def _update_buttons(self) -> None:
        self.run_button.setVisible(not (self._running or self._asking))
        self.send_button.setVisible(self._asking)
        self.cancel_button.setVisible(self._running or self._asking)
        self.run_button.setEnabled(self._can_run and bool(self.command.text().strip()))

    # -- Acciones ----------------------------------------------

    def _run(self) -> None:
        if not self._running and self.run_button.isEnabled():
            self.coordinator.run(self.command.text())
            self.command.clear()

    def _send_password(self) -> None:
        if self._asking:
            password = self.password.text()
            self.password.clear()
            self.coordinator.give_password(password)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt)
        """Flechas arriba y abajo en la linea de comando: lo ya corrido; Ctrl+L limpia."""
        if watched is self.command and event.type() == QEvent.Type.KeyPress:
            ctrl = event.modifiers() == Qt.KeyboardModifier.ControlModifier
            if ctrl and event.key() == Qt.Key.Key_L:
                self.coordinator.clear()
                return True
            if event.key() == Qt.Key.Key_Up:
                self.command.setText(self.coordinator.history_older(self.command.text()))
                return True
            if event.key() == Qt.Key.Key_Down:
                self.command.setText(self.coordinator.history_newer())
                return True
        return super().eventFilter(watched, event)

    def _choose(self, name: str) -> None:
        if name:
            self.coordinator.choose(name)

    def closeEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        self.coordinator.close()
        super().closeEvent(event)
