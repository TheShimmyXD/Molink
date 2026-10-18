"""La barra lateral cambia de modulo: un boton por modulo, el elegido queda marcado."""

from __future__ import annotations

from config import AppConfig
from logic._00_logic_main import NAVIGATION_ITEMS
from modules.mod_02_pair._02_coordinator_preview import PreviewPairCoordinator
from modules.mod_05_chat._05_coordinator_preview import PreviewChatCoordinator
from ui._00_ui_main import MainWindow
from ui._00_ui_sidebar import COLLAPSED_WIDTH, EXPANDED_WIDTH


def _window(chat: PreviewChatCoordinator | None = None) -> MainWindow:
    return MainWindow(
        config=AppConfig(),
        save_config=lambda _config: True,
        pair_coordinator=PreviewPairCoordinator,
        chat_coordinator=lambda: chat or PreviewChatCoordinator("ready"),
    )


def test_one_button_per_module(qt_application):
    window = _window()
    expected = [item.module_id for item in NAVIGATION_ITEMS]
    assert list(window._nav_buttons) == expected
    window.close()


def test_sidebar_switches_module(qt_application):
    window = _window()
    first = window.workspace_stack.currentWidget()
    assert window._nav_buttons["pair"].isChecked()

    window._nav_buttons["console"].click()
    assert window.logic.active_module_id == "console"
    assert window._nav_buttons["console"].isChecked()
    assert not window._nav_buttons["pair"].isChecked()
    assert window.workspace_stack.currentWidget() is not first

    window._nav_buttons["pair"].click()
    assert window.workspace_stack.currentWidget() is first
    window.close()


def test_sidebar_expands_with_labels(qt_application):
    window = _window()
    window.resize(660, 400)
    button = window._nav_buttons["console"]
    assert button.text() == ""
    assert window.sidebar.width() == COLLAPSED_WIDTH

    window.sidebar.set_expanded(True)
    assert "Consola" in button.text()
    assert "Tema" in window.theme_button.text()
    window.sidebar.place(0, 0, window.height())
    assert window.sidebar.width() == EXPANDED_WIDTH

    window.sidebar.set_expanded(False)
    window.sidebar.place(0, 0, window.height())
    window.sidebar._on_animation_finished()
    assert button.text() == ""
    assert window.sidebar.width() == COLLAPSED_WIDTH
    window.close()


def test_theme_button_cycles_without_writing(qt_application):
    saved = []
    window = MainWindow(
        config=AppConfig(theme="light"),
        save_config=saved.append,
        pair_coordinator=PreviewPairCoordinator,
        chat_coordinator=lambda: PreviewChatCoordinator("ready"),
    )
    window.theme_button.click()
    assert window._config.theme == "dark"
    assert [config.theme for config in saved] == ["dark"]
    assert "oscuro" in window.theme_button.toolTip()
    window.close()


def test_chat_starts_with_the_window_and_marks_its_button(qt_application):
    chat = PreviewChatCoordinator("talk")
    window = _window(chat)
    assert chat.calls[0] == ("start",)
    button = window._nav_buttons["chat"]
    chat.emit_badge()
    assert "chat" in window.sidebar._badges
    assert (
        "3 sin leer" in button.toolTip() and "Enviando fotos_taller.zip: 37 %" in button.toolTip()
    )

    chat.logic = PreviewChatCoordinator("ready").logic
    chat.emit_badge()
    assert "chat" not in window.sidebar._badges and "sin leer" not in button.toolTip()

    window._nav_buttons["chat"].click()
    assert window.workspace_stack.currentWidget().coordinator is chat
    window.close()
    assert ("close",) in chat.calls
