"""Coordinador sin red para las capturas y las pruebas de pantalla del Chat.

Sirve una vista fija de ejemplo (equipo 'sobremesa', IP 192.0.2.20; nunca
datos reales ni mensajes de verdad) y anota lo que la UI le pide. No abre
puertos ni toca el enlace.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from modules.mod_05_chat.logic._05_logic_chat import ChatLogic

PEER = ("sobremesa", "192.0.2.20")
OTHER = ("taller", "192.0.2.30")
MB = 1024 * 1024
# 18:02 de hoy en hora local: las capturas muestran siempre las mismas horas.
_today = time.localtime()
START = time.mktime((*_today[:3], 18, 2, 0, 0, 0, -1))


def _ready(logic: ChatLogic) -> None:
    logic.set_targets([PEER, OTHER])


def _talk(logic: ChatLogic) -> None:
    """Una conversacion con cada tipo de burbuja; el ultimo archivo de cada lado en camino."""
    _ready(logic)
    logic.received(PEER[0], "m1", "¿Ya te llegó el informe?", START)
    logic.text_finished(logic.write("Todavía no, te lo paso ahora", START + 60)["entry_id"], True)
    logic.add_files([(Path("informe_final.pdf"), int(4.2 * MB))], 0, START + 70)
    logic.file_finished(logic.start_next_file()["entry_id"], True, "informe_final.pdf")
    logic.received(PEER[0], "m2", "Listo, gracias. Mándame también las fotos", START + 120)
    logic.add_files([(Path("fotos_taller.zip"), 48 * MB), (Path("notas.txt"), 900)], 0, START + 180)
    logic.file_progress(logic.start_next_file()["entry_id"], int(17.8 * MB))
    logic.incoming(PEER[0], 1, "START", "planos_v3.dwg", 0, int(12.7 * MB), START + 190)
    logic.incoming(PEER[0], 1, "PROGRESS", "", int(8.1 * MB), 0, START + 190)
    logic.write("¿Te llegan bien?", START + 200)


def _failed(logic: ChatLogic) -> None:
    """Lo que no termino: un mensaje sin acuse, un envio cancelado y una llegada cortada."""
    _ready(logic)
    logic.add_files([(Path("video.mp4"), 300 * MB)], 0, START)
    entry_id = logic.start_next_file()["entry_id"]
    logic.file_progress(entry_id, 90 * MB)
    logic.cancel_file(entry_id)
    logic.incoming(PEER[0], 2, "START", "respaldo.tar", 0, 80 * MB, START + 30)
    logic.incoming(PEER[0], 2, "CUT", "", 20 * MB, 0, START + 40)
    entry_id = logic.write("¿Se cortó?", START + 60)["entry_id"]
    logic.text_finished(
        entry_id, False, "No se pudo entregar.", "Revisa que Molink siga abierto allá."
    )
    logic.add_files([], 1, START + 70)  # una carpeta soltada


def _offline(logic: ChatLogic) -> None:
    _talk(logic)
    logic.set_targets([OTHER])


SAMPLES = {
    "no_target": lambda logic: None,
    "ready": _ready,
    "talk": _talk,
    "failed": _failed,
    "offline": _offline,
}


class PreviewChatCoordinator(QObject):
    view_changed = Signal(object)
    badge_changed = Signal(object)

    def __init__(self, sample: str = "talk", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.logic = ChatLogic()
        SAMPLES[sample](self.logic)
        self.calls: list[tuple] = []

    def view(self) -> dict:
        return self.logic.view()

    def start(self) -> None:
        self.calls.append(("start",))

    def refresh(self) -> None:
        self.calls.append(("refresh",))

    def set_visible(self, visible: bool) -> None:
        self.calls.append(("set_visible", visible))

    def choose(self, name: str) -> None:
        self.calls.append(("choose", name))

    def write(self, text: str) -> bool:
        self.calls.append(("write", text))
        return bool(text.strip())

    def send(self, paths: list[Path]) -> None:
        self.calls.append(("send", list(paths)))

    def cancel(self, entry_id: int) -> None:
        self.calls.append(("cancel", entry_id))

    def open_inbox(self) -> str:
        self.calls.append(("open_inbox",))
        return ""

    def emit_badge(self) -> None:
        """Las pruebas de la ventana lo usan para mirar el punto del boton."""
        self.badge_changed.emit(self.logic.badge())

    def close(self) -> None:
        self.calls.append(("close",))
