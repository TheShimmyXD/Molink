from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from logic._00_logic_targets import Outcome, human_size
from logic._00_logic_targets import Tone as OutcomeTone
from modules.mod_05_chat.logic._05_logic_chat import Entry, EntryKind, EntryState
from ui.blocks.icons import GlyphButton, GlyphLabel
from ui.theme import Kind, Tone, mono_font, set_drag_active, set_kind, set_tone

TARGET_WIDTH = 150
BUBBLE_WIDTH = 340  # medido en la maqueta A: dos burbujas no se tocan a 660 px
STICK_PX = 8  # a esta distancia del fondo, lo nuevo baja la conversacion
OUTCOME_TONES = {
    OutcomeTone.NEUTRAL: Tone.MUTED,
    OutcomeTone.OK: Tone.OK,
    OutcomeTone.WARNING: Tone.WARNING,
    OutcomeTone.ERROR: Tone.ERROR,
}
# Icono pequeno junto a la hora: (glifo, tono, ayuda); None no muestra nada.
STATE_GLYPHS = {
    EntryState.QUEUED: ("clock", Tone.MUTED, "En cola"),
    EntryState.SENDING: ("clock", Tone.MUTED, "Enviando"),
    EntryState.DELIVERED: ("checks", Tone.OK, "Entregado"),
    EntryState.RECEIVING: None,
    EntryState.RECEIVED: None,
    EntryState.FAILED: ("warning-circle", Tone.ERROR, "No llegó"),
    EntryState.CANCELLED: ("prohibit", Tone.MUTED, "Cancelado"),
    EntryState.CUT: ("warning-circle", Tone.WARNING, "Se cortó"),
}
MOVING = (EntryState.SENDING, EntryState.RECEIVING)
CANCELLABLE = (EntryState.QUEUED, EntryState.SENDING)


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    set_tone(label, Tone.MUTED)
    return label


def _mono(text: str = "", muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setFont(mono_font())
    if muted:
        set_tone(label, Tone.MUTED)
    return label


def _local_paths(mime) -> list[Path]:
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]


def _hour(at: float) -> str:
    return time.strftime("%H:%M", time.localtime(at))


def _file_detail(entry: Entry) -> str:
    size = human_size(entry.size)
    if entry.state == EntryState.QUEUED:
        return f"en cola, {size}"
    if entry.state in MOVING:
        return f"{entry.percent} % de {size}"
    if entry.state == EntryState.CANCELLED:
        return f"cancelado a {entry.percent} %"
    if entry.state == EntryState.CUT:
        return f"se cortó a {entry.percent} %"
    return size


def _note(entry: Entry) -> tuple[str, Tone]:
    """Lo que va bajo el contenido: el nombre con que quedo o por que no llego."""
    if entry.state == EntryState.FAILED:
        return " ".join(part for part in (entry.note, entry.hint) if part), Tone.ERROR
    if entry.note and entry.state == EntryState.DELIVERED:
        return f"Allá quedó como {entry.note}", Tone.MUTED
    if entry.note and entry.state == EntryState.RECEIVED:
        return f"Se guardó como {entry.note}", Tone.MUTED
    return "", Tone.MUTED


class _Bubble(QFrame):
    """Un mensaje o un archivo; se repinta con show_entry cuando cambia."""

    def __init__(
        self, entry: Entry, on_cancel: Callable[[int], None], on_open: Callable[[], None]
    ) -> None:
        super().__init__()
        set_kind(self, Kind.BUBBLE_OUT if entry.outgoing else Kind.BUBBLE_IN)
        self.setMaximumWidth(BUBBLE_WIDTH)
        self.entry: Entry | None = None
        col = QVBoxLayout(self)
        col.setContentsMargins(10, 6, 10, 6)
        col.setSpacing(3)

        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.file_row = QWidget()
        head = QHBoxLayout(self.file_row)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        glyph = "file-arrow-up" if entry.outgoing else "file-arrow-down"
        head.addWidget(GlyphLabel(glyph, 22, Tone.INFO))
        self.name = QLabel()
        self.name.setWordWrap(True)
        self.name.setMinimumWidth(140)
        head.addWidget(self.name, 1)
        self.cancel_button = GlyphButton("x", "Cancelar el envío", 14)
        self.cancel_button.clicked.connect(lambda: on_cancel(entry.entry_id))
        head.addWidget(self.cancel_button)
        self.open_button = GlyphButton("folder-open", "Abrir la carpeta de llegada", 14)
        self.open_button.clicked.connect(on_open)
        head.addWidget(self.open_button)
        is_file = entry.kind == EntryKind.FILE
        col.addWidget(self.file_row if is_file else self.text)
        (self.text if is_file else self.file_row).hide()

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        col.addWidget(self.bar)
        self.note = QLabel()
        self.note.setWordWrap(True)
        col.addWidget(self.note)

        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.detail = _mono(muted=True)
        self.hour = _muted()
        self.state_icon = GlyphLabel("clock", 12, Tone.MUTED)
        foot.addWidget(self.detail, 1)
        foot.addWidget(self.hour)
        foot.addWidget(self.state_icon)
        col.addLayout(foot)
        self.show_entry(entry)

    def show_entry(self, entry: Entry) -> None:
        if entry == self.entry:
            return
        self.entry = entry
        is_file = entry.kind == EntryKind.FILE
        if is_file:
            self.name.setText(entry.text)
            self.cancel_button.setVisible(entry.outgoing and entry.state in CANCELLABLE)
            self.open_button.setVisible(entry.state == EntryState.RECEIVED)
            self.bar.setValue(entry.percent)
        else:
            self.text.setText(entry.text)
        self.bar.setVisible(is_file and entry.state in MOVING)
        self.detail.setText(_file_detail(entry) if is_file else "")
        self.hour.setText(_hour(entry.at))
        note, tone = _note(entry)
        self.note.setVisible(bool(note))
        self.note.setText(note)
        set_tone(self.note, tone)
        shown = STATE_GLYPHS[entry.state]
        self.state_icon.setVisible(shown is not None)
        if shown is not None:
            glyph, glyph_tone, tip = shown
            self.state_icon.set_glyph(glyph, glyph_tone)
            self.state_icon.setToolTip(tip)


class ChatWidget(QWidget):
    """
    Chat en una columna: arriba el equipo, en medio la conversacion con
    burbujas (lo que sale a la derecha) y abajo el clip, el campo y enviar.
    Soltar archivos en cualquier parte de la pantalla los envia.

    Solo habla con el coordinador, que crea la ventana al arrancar: esta
    pantalla no lo arranca ni lo cierra, solo le avisa si se esta viendo.
    """

    def __init__(self, coordinator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.coordinator = coordinator
        self._rows: dict[int, tuple[QWidget, _Bubble]] = {}
        self._shown_peer = ""
        self._stick = True
        self._can_write = False
        self.setAcceptDrops(True)
        self._build_ui()
        coordinator.view_changed.connect(self.render)
        self.render(coordinator.view())

    def _build_ui(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 10, 16, 12)
        col.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.status_icon = GlyphLabel("check-circle", 16, Tone.OK)
        self.target = QComboBox()
        self.target.setMinimumWidth(TARGET_WIDTH)
        self.target.setToolTip("Equipo emparejado con quien conversas")
        self.target.activated.connect(self._choose)
        self.address = _mono(muted=True)
        self.status_text = _muted()
        self.status_text.setWordWrap(True)
        top.addWidget(self.status_icon)
        top.addWidget(self.target)
        top.addWidget(self.address)
        top.addWidget(self.status_text, 1)
        col.addLayout(top)
        rule = QFrame()
        set_kind(rule, Kind.RULE)
        rule.setFixedHeight(1)
        col.addWidget(rule)

        self.conversation = QScrollArea()
        set_kind(self.conversation, Kind.CHAT)
        self.conversation.setWidgetResizable(True)
        self.conversation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.entries = QVBoxLayout(inner)
        self.entries.setContentsMargins(0, 4, 4, 4)
        self.entries.setSpacing(6)
        self.entries.addStretch(1)  # lo ultimo queda abajo, junto al campo
        self.conversation.setWidget(inner)
        bar = self.conversation.verticalScrollBar()
        bar.valueChanged.connect(self._track_bottom)
        bar.rangeChanged.connect(self._keep_bottom)
        col.addWidget(self.conversation, 1)

        self.outcome = QLabel()
        self.outcome.setWordWrap(True)
        col.addWidget(self.outcome)

        composer = QHBoxLayout()
        composer.setSpacing(6)
        self.clip_button = GlyphButton("paperclip", "Elegir archivos para enviar")
        self.clip_button.clicked.connect(self._pick)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Escribe un mensaje o suelta archivos aquí")
        self.entry.setAcceptDrops(False)  # un archivo soltado encima se envia, no se pega
        self.entry.returnPressed.connect(self._send_text)
        self.send_button = GlyphButton("paper-plane-right", "Enviar (Enter)")
        self.send_button.clicked.connect(self._send_text)
        composer.addWidget(self.clip_button)
        composer.addWidget(self.entry, 1)
        composer.addWidget(self.send_button)
        col.addLayout(composer)

    # -- Pintar la vista ---------------------------------------

    def render(self, view: dict) -> None:
        self._render_target(view)
        self._render_entries(view["target"], view["entries"])
        outcome: Outcome | None = view["outcome"]
        self.outcome.setVisible(outcome is not None)
        if outcome is not None:
            self.outcome.setText(outcome.text + (f" {outcome.hint}" if outcome.hint else ""))
            set_tone(self.outcome, OUTCOME_TONES[outcome.tone])
        self._can_write = view["state"] == "READY"
        for widget in (self.clip_button, self.entry, self.send_button):
            widget.setEnabled(self._can_write)

    def _render_target(self, view: dict) -> None:
        status: Outcome | None = view["status"]
        peers = view["peers"]
        self.target.setVisible(bool(peers))
        self.address.setVisible(view["state"] == "READY")
        self.address.setText(view["address"])
        if status is None:
            self.status_icon.set_glyph("check-circle", Tone.OK)
            self.status_text.setText("en la red")
        else:
            self.status_icon.set_glyph("plugs", Tone.MUTED)
            self.status_text.setText(f"{status.text} {status.hint}".strip())
        labels = [
            (p["name"], p["name"] + (f" ({p['unread']})" if p["unread"] else "")) for p in peers
        ]
        shown = [
            (self.target.itemData(i), self.target.itemText(i)) for i in range(self.target.count())
        ]
        if labels != shown:
            self.target.blockSignals(True)
            self.target.clear()
            for name, label in labels:
                self.target.addItem(label, name)
            self.target.blockSignals(False)
        index = self.target.findData(view["target"])
        if index >= 0:
            self.target.setCurrentIndex(index)

    def _render_entries(self, peer: str, entries: list[Entry]) -> None:
        if peer != self._shown_peer:
            self._clear()
            self._shown_peer = peer
            self._stick = True
        alive = {entry.entry_id for entry in entries}
        for entry_id in [i for i in self._rows if i not in alive]:
            row, _ = self._rows.pop(entry_id)
            row.deleteLater()
        for entry in entries:
            if entry.entry_id in self._rows:
                self._rows[entry.entry_id][1].show_entry(entry)
            else:
                self._add_row(entry)

    def _add_row(self, entry: Entry) -> None:
        bubble = _Bubble(entry, self.coordinator.cancel, self._open_inbox)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        if entry.outgoing:
            line.addStretch(1)
        line.addWidget(bubble)
        if not entry.outgoing:
            line.addStretch(1)
        self.entries.addWidget(row)
        self._rows[entry.entry_id] = (row, bubble)
        if entry.outgoing:
            self._stick = True  # lo que escribo yo siempre se ve

    def _clear(self) -> None:
        for row, _ in self._rows.values():
            row.deleteLater()
        self._rows.clear()

    def _track_bottom(self, value: int) -> None:
        self._stick = value >= self.conversation.verticalScrollBar().maximum() - STICK_PX

    def _keep_bottom(self, _minimum: int, maximum: int) -> None:
        if self._stick:
            self.conversation.verticalScrollBar().setValue(maximum)

    # -- Acciones ----------------------------------------------

    def _send_text(self) -> None:
        if self.coordinator.write(self.entry.text()):
            self.entry.clear()

    def _pick(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Elegir archivos para enviar")
        if names:
            self.coordinator.send([Path(name) for name in names])

    def _open_inbox(self) -> None:
        path = self.coordinator.open_inbox()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _choose(self, index: int) -> None:
        name = self.target.itemData(index)
        if name:
            self.coordinator.choose(name)

    # -- Soltar archivos y visibilidad -------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        if self._can_write and _local_paths(event.mimeData()):
            event.acceptProposedAction()
            set_drag_active(self.conversation, True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        set_drag_active(self.conversation, False)

    def dropEvent(self, event) -> None:  # noqa: N802
        set_drag_active(self.conversation, False)
        paths = _local_paths(event.mimeData())
        if paths and self._can_write:
            event.acceptProposedAction()
            self.coordinator.send(paths)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.coordinator.set_visible(True)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.coordinator.set_visible(False)
        super().hideEvent(event)
