from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from modules.mod_05_chat._05_coordinator_preview import PreviewChatCoordinator
from modules.mod_05_chat.ui._05_ui_chat import ChatWidget
from ui.theme import Kind


def _widget(sample: str) -> tuple[ChatWidget, PreviewChatCoordinator]:
    coordinator = PreviewChatCoordinator(sample)
    return ChatWidget(coordinator=coordinator), coordinator


def _bubbles(widget: ChatWidget):
    return [bubble for _, bubble in widget._rows.values()]


def _drop(widget: ChatWidget, urls: list[QUrl]) -> None:
    mime = QMimeData()
    mime.setUrls(urls)
    event = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(event)


def test_no_target_disables_writing(qt_application):
    widget, coordinator = _widget("no_target")
    assert ("start",) not in coordinator.calls  # lo arranca la ventana, no la pantalla
    assert widget.target.isHidden() and not _bubbles(widget)
    assert widget.status_text.text().startswith("Ningún equipo")
    assert not widget.entry.isEnabled() and not widget.clip_button.isEnabled()


def test_conversation_shows_each_kind_of_bubble(qt_application):
    widget, _ = _widget("talk")
    bubbles = _bubbles(widget)
    assert len(bubbles) == 8
    assert widget.target.itemText(0) == "sobremesa (3)" and widget.target.itemData(0) == "sobremesa"
    assert bubbles[0].property("kind") == Kind.BUBBLE_IN.value
    assert bubbles[1].property("kind") == Kind.BUBBLE_OUT.value
    sending, queued, receiving = bubbles[4], bubbles[5], bubbles[6]
    assert sending.name.text() == "fotos_taller.zip" and sending.bar.value() == 37
    assert not sending.bar.isHidden() and not sending.cancel_button.isHidden()
    assert queued.detail.text() == "en cola, 900 B" and queued.bar.isHidden()
    assert receiving.detail.text() == "63 % de 12,7 MB" and receiving.cancel_button.isHidden()
    assert bubbles[2].state_icon.toolTip() == "Entregado"


def test_cancel_in_a_bubble_cancels_that_file(qt_application):
    widget, coordinator = _widget("talk")
    sending = _bubbles(widget)[4]
    sending.cancel_button.click()
    assert coordinator.calls[-1] == ("cancel", sending.entry.entry_id)


def test_enter_writes_and_clears(qt_application):
    widget, coordinator = _widget("ready")
    assert not _bubbles(widget) and widget.entry.isEnabled()
    widget.entry.setText("hola")
    widget.entry.returnPressed.emit()
    assert coordinator.calls[-1] == ("write", "hola") and widget.entry.text() == ""
    widget.entry.setText("   ")
    widget.send_button.click()
    assert coordinator.calls[-1] == ("write", "   ") and widget.entry.text() == "   "


def test_failures_show_why(qt_application):
    widget, _ = _widget("failed")
    cancelled, cut, failed = _bubbles(widget)
    assert cancelled.detail.text() == "cancelado a 30 %"
    assert cut.detail.text() == "se cortó a 25 %"
    assert failed.note.text().startswith("No se pudo entregar.")
    assert widget.outcome.text().startswith("Se omitieron 1")


def test_offline_keeps_the_conversation_readonly(qt_application):
    widget, _ = _widget("offline")
    assert len(_bubbles(widget)) == 8
    assert widget.status_text.text().startswith("sobremesa salió de la red.")
    assert not widget.entry.isEnabled() and widget.address.isHidden()


def test_drop_sends_local_files_only_when_ready(qt_application, tmp_path):
    widget, coordinator = _widget("ready")
    _drop(widget, [QUrl.fromLocalFile(str(tmp_path / "a.txt")), QUrl("https://example.com/x")])
    assert coordinator.calls[-1] == ("send", [Path(tmp_path / "a.txt")])

    widget, coordinator = _widget("no_target")
    _drop(widget, [QUrl.fromLocalFile(str(tmp_path / "a.txt"))])
    assert not any(call[0] == "send" for call in coordinator.calls)


def test_choosing_another_peer_redraws(qt_application):
    widget, coordinator = _widget("talk")
    widget._choose(1)
    assert coordinator.calls[-1] == ("choose", "taller")
    coordinator.logic.choose("taller")
    widget.render(coordinator.view())
    assert not _bubbles(widget)


def test_showing_and_hiding_tell_the_coordinator(qt_application):
    widget, coordinator = _widget("ready")
    widget.show()
    widget.hide()
    assert coordinator.calls[-2:] == [("set_visible", True), ("set_visible", False)]


def test_received_file_opens_the_arrival_folder(qt_application):
    widget, coordinator = _widget("talk")
    receiving = _bubbles(widget)[6]
    assert receiving.open_button.isHidden()
    coordinator.logic.incoming("sobremesa", 1, "DONE", "planos_v3.dwg", 100, 0, 0.0)
    widget.render(coordinator.view())
    assert not receiving.open_button.isHidden() and receiving.bar.isHidden()
    receiving.open_button.click()
    assert coordinator.calls[-1] == ("open_inbox",)
