"""Pantalla de la consola con el coordinador de muestras: sin red ni carpeta de datos."""

from __future__ import annotations

from modules.mod_03_console._03_coordinator_preview import PreviewConsoleCoordinator
from modules.mod_03_console.ui._03_ui_console import ConsoleWidget


def test_run_by_enter_clears_and_cancel_only_while_running(qt_application):
    coordinator = PreviewConsoleCoordinator("ready")
    widget = ConsoleWidget(coordinator)
    assert coordinator.calls == [("start",)]
    assert not widget.run_button.isEnabled() and widget.cancel_button.isHidden()
    widget.command.setText("hostname")
    widget.command.returnPressed.emit()
    assert coordinator.calls[-1] == ("run", "hostname") and widget.command.text() == ""

    running = ConsoleWidget(PreviewConsoleCoordinator("running"))
    assert running.run_button.isHidden() and not running.cancel_button.isHidden()
    assert not running.target.isEnabled() and "icmp_seq=4" in running.output.toPlainText()
    running.cancel_button.click()
    assert running.coordinator.calls[-1] == ("cancel",)
    running.close()
    assert running.coordinator.calls[-1] == ("close",)


def test_no_target_shows_what_to_do_and_blocks_run(qt_application):
    widget = ConsoleWidget(PreviewConsoleCoordinator("no_target"))
    widget.command.setText("hostname")
    assert widget.target.isHidden() and not widget.status_text.isHidden()
    assert "Emparejar" in widget.status_text.text() and not widget.run_button.isEnabled()
    widget.command.returnPressed.emit()
    assert ("run", "hostname") not in widget.coordinator.calls


def test_failed_outcome_carries_its_hint(qt_application):
    widget = ConsoleWidget(PreviewConsoleCoordinator("failed"))
    assert widget.outcome.text().startswith("No se pudo conectar a 192.0.2.20:47820.")
    assert "cortafuegos" in widget.outcome.text() and widget.target.currentText() == "sobremesa"


def test_prompt_shows_the_folder_and_arrows_walk_the_history(qt_application):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    widget = ConsoleWidget(PreviewConsoleCoordinator("folder"))
    assert widget.prompt.text() == "~/Descargas $" and widget.password.isHidden()
    widget.command.setText("a medias")
    QTest.keyClick(widget.command, Qt.Key.Key_Up)
    assert widget.command.text() == "ls"
    QTest.keyClick(widget.command, Qt.Key.Key_Up)
    assert widget.command.text() == "cd Descargas"
    QTest.keyClick(widget.command, Qt.Key.Key_Down)
    QTest.keyClick(widget.command, Qt.Key.Key_Down)
    assert widget.command.text() == "a medias"


def test_sudo_asks_in_a_hidden_field_that_is_emptied_on_send(qt_application):
    coordinator = PreviewConsoleCoordinator("asking")
    widget = ConsoleWidget(coordinator)
    assert widget.command.isHidden() and widget.prompt.isHidden()
    assert not widget.password.isHidden() and not widget.send_button.isHidden()
    assert widget.run_button.isHidden() and not widget.cancel_button.isHidden()
    assert widget.password.echoMode() == widget.password.EchoMode.Password
    assert widget.outcome.text() == "sudo pide la contraseña de sobremesa. No se guarda."
    assert not widget.target.isEnabled()
    widget.password.setText("clave")
    widget.password.returnPressed.emit()
    assert coordinator.calls[-1] == ("give_password", 5) and widget.password.text() == ""
    widget.cancel_button.click()
    assert coordinator.calls[-1] == ("cancel",)


def test_clear_and_ctrl_l_empty_the_output_without_running(qt_application):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    coordinator = PreviewConsoleCoordinator("done")
    widget = ConsoleWidget(coordinator)
    assert widget.output.toPlainText()
    QTest.keyClick(widget.command, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    assert coordinator.calls[-1] == ("clear",) and widget.output.toPlainText() == ""
