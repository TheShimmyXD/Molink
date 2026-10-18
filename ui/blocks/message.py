from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

_ICONS = {
    "information": QMessageBox.Icon.Information,
    "warning": QMessageBox.Icon.Warning,
    "critical": QMessageBox.Icon.Critical,
    "question": QMessageBox.Icon.Question,
}


def message_box(
    parent: QWidget | None, title: str, message: str, icon: str = "information"
) -> None:
    """Muestra un mensaje modal con el ícono indicado ('information', 'warning'...)."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(_ICONS.get(icon, QMessageBox.Icon.Information))
    box.exec()


def confirm(parent: QWidget | None, title: str, message: str) -> bool:
    """Pregunta Sí/No. Devuelve True si el usuario acepta."""
    answer = QMessageBox.question(
        parent,
        title,
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes
