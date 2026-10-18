"""Coordinador sin red para las capturas y las pruebas de pantalla.

Sirve una vista fija de ejemplo (equipo 'sobremesa', IP 192.0.2.20, codigo
000000; nunca datos reales) y anota lo que la UI le pide. No abre puertos ni
lee la carpeta de datos de Molink.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from modules.mod_02_pair.logic._02_logic_pair import PairLogic

HOST = "192.0.2.10"
PEER = ("sobremesa", "192.0.2.20")
OTHER = ("taller", "192.0.2.30")
CODE = "000000"


def _starting(logic: PairLogic) -> None:
    logic.link_starting(HOST)


def _searching(logic: PairLogic) -> None:
    logic.link_starting(HOST)
    logic.link_started(47820)


def _found(logic: PairLogic) -> None:
    _searching(logic)
    logic.set_paired([OTHER[0]])
    logic.peers_found([PEER, OTHER])


def _joining(logic: PairLogic) -> None:
    _found(logic)
    logic.start_join(PEER[0], CODE)


def _join_error(logic: PairLogic) -> None:
    _joining(logic)
    logic.join_finished(
        PEER[0],
        False,
        "El código no coincide o la ventana ya se cerró.",
        "Revisa el código; si se acabó el tiempo, pide uno nuevo allá.",
    )


def _paired(logic: PairLogic) -> None:
    _joining(logic)
    logic.join_finished(PEER[0], True)


def _window(logic: PairLogic) -> None:
    _found(logic)
    logic.window_opened(CODE, 47821, 112.0, now=0.0)


def _error(logic: PairLogic) -> None:
    logic.link_starting(HOST)
    logic.link_failed(
        "El puerto 47820 ya está ocupado.",
        "¿Hay otro Molink abierto en este equipo? Ciérralo y reintenta.",
    )


def _lost(logic: PairLogic) -> None:
    _found(logic)
    logic.link_lost()
    logic.schedule_retry(0.0, 4.0)


SAMPLES = {
    "starting": _starting,
    "searching": _searching,
    "found": _found,
    "joining": _joining,
    "join_error": _join_error,
    "paired": _paired,
    "window": _window,
    "error": _error,
    "lost": _lost,
}


class PreviewPairCoordinator(QObject):
    view_changed = Signal(object)
    connection_changed = Signal(object)

    def __init__(self, sample: str = "found", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.logic = PairLogic()
        SAMPLES[sample](self.logic)
        self.calls: list[tuple] = []

    def view(self) -> dict:
        return self.logic.view(0.0)

    def connection(self):
        return self.logic.connection(0.0)

    def start(self) -> None:
        self.calls.append(("start",))

    def join(self, name: str, code: str) -> None:
        self.calls.append(("join", name, len(code)))

    def open_window(self) -> None:
        self.calls.append(("open_window",))

    def close_window(self) -> None:
        self.calls.append(("close_window",))

    def forget(self, name: str) -> None:
        self.calls.append(("forget", name))

    def close(self) -> None:
        self.calls.append(("close",))
