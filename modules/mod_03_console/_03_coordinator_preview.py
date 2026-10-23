"""Coordinador sin red para las capturas y las pruebas de pantalla de la consola.

Sirve una vista fija de ejemplo (equipo 'sobremesa', IP 192.0.2.20; nunca
datos reales) con una salida inventada y anota lo que la UI le pide. No abre
puertos ni lee la carpeta de datos de Molink.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from logic._00_logic_platform import OS_WINDOWS
from modules.mod_03_console.logic._03_logic_console import ConsoleLogic
from modules.mod_03_console.logic._03_logic_shell import Place

PEER = ("sobremesa", "192.0.2.20")
OTHER = ("taller", "192.0.2.30")
HOME = "/home/ana"
WIN_HOME = "C:\\Users\\ana"
WINDOWS = (
    "PS ~> cd Desktop\nPS ~\\Desktop> dir\n\n    Directorio: C:\\Users\\ana\\Desktop\n\n"
    "Mode          LastWriteTime   Length Name\n----          -------------   ------ ----\n"
    "-a----  23/10/2026  18:02    10240 notas.txt\nPS ~\\Desktop> sudo winget upgrade\n"
)
HISTORY = "~ $ hostname\nsobremesa\n~ $ ls ~/Descargas\nnotas.txt  fotos  molink-0.1.tar.gz\n"
FOLDER = "~ $ cd Descargas\n~/Descargas $ ls\nnotas.txt  fotos  molink-0.1.tar.gz\n"
RUNNING = "~ $ ping -c 20 192.0.2.1\n" + "".join(
    f"64 bytes from 192.0.2.1: icmp_seq={n} ttl=64 time=1.{n} ms\n" for n in range(1, 5)
)


def _ready(logic: ConsoleLogic) -> str:
    logic.set_targets([PEER, OTHER])
    return ""


def _done(logic: ConsoleLogic) -> str:
    _ready(logic)
    logic.start_run("ls ~/Descargas", 0.0)
    logic.run_finished(True, 0, 0.4)
    return HISTORY


def _running(logic: ConsoleLogic) -> str:
    _ready(logic)
    logic.start_run("ping -c 20 192.0.2.1", 0.0)
    return HISTORY + RUNNING


def _cancelled(logic: ConsoleLogic) -> str:
    _running(logic)
    logic.cancel(4.2)
    return HISTORY + RUNNING


def _failed(logic: ConsoleLogic) -> str:
    _ready(logic)
    logic.start_run("df -h", 0.0)
    logic.run_finished(
        False,
        None,
        10.0,
        "No se pudo conectar a 192.0.2.20:47820.",
        "¿Molink está abierto allá? Si lo está, revisa su cortafuegos.",
    )
    return HISTORY + "~ $ df -h\n"


def _folder(logic: ConsoleLogic) -> str:
    _ready(logic)
    for command, took in (("cd Descargas", 0.1), ("ls", 0.2)):
        logic.start_run(command, 0.0)
        logic.run_finished(True, 0, took, place=Place(f"{HOME}/Descargas", HOME))
    return FOLDER


def _asking(logic: ConsoleLogic) -> str:
    _folder(logic)
    logic.start_run("sudo apt update", 0.0)
    return FOLDER + "~/Descargas $ sudo apt update\n"


def _windows(logic: ConsoleLogic) -> str:
    logic.set_targets([OTHER, PEER], {OTHER[0]: OS_WINDOWS})
    for command in ("cd Desktop", "dir"):
        logic.start_run(command, 0.0)
        logic.run_finished(True, 0, 0.3, place=Place(WIN_HOME + "\\Desktop", WIN_HOME))
    logic.start_run("sudo winget upgrade", 0.0)
    return WINDOWS


SAMPLES = {
    "no_target": lambda logic: "",
    "ready": _ready,
    "done": _done,
    "running": _running,
    "cancelled": _cancelled,
    "failed": _failed,
    "folder": _folder,
    "asking": _asking,
    "windows": _windows,
}


class PreviewConsoleCoordinator(QObject):
    view_changed = Signal(object)
    output_added = Signal(str)
    output_cleared = Signal()

    def __init__(self, sample: str = "done", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.logic = ConsoleLogic()
        self._output = SAMPLES[sample](self.logic)
        self.calls: list[tuple] = []

    def view(self) -> dict:
        return self.logic.view()

    def start(self) -> None:
        self.calls.append(("start",))
        if self._output:
            self.output_added.emit(self._output)

    def refresh(self) -> None:
        self.calls.append(("refresh",))

    def choose(self, name: str) -> None:
        self.calls.append(("choose", name))

    def run(self, command: str) -> None:
        self.calls.append(("run", command))

    def clear(self) -> None:
        self.calls.append(("clear",))
        self.output_cleared.emit()

    def give_password(self, password: str) -> None:
        self.calls.append(("give_password", len(password)))  # nunca el texto

    def history_older(self, current: str) -> str:
        self.calls.append(("history_older", current))
        return self.logic.history.older(current)

    def history_newer(self) -> str:
        self.calls.append(("history_newer",))
        return self.logic.history.newer()

    def cancel(self) -> None:
        self.calls.append(("cancel",))

    def close(self) -> None:
        self.calls.append(("close",))
