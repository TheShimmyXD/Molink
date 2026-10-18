from __future__ import annotations

import concurrent.futures
import time
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from core.async_loop import AsyncLoop
from core.link_worker import LinkWorker
from modules.mod_03_console.logic._03_logic_console import ConsoleLogic, OutputDecoder
from modules.mod_03_console.logic._03_logic_shell import STDERR, Place, ShellMarkFilter
from services.service_link import LinkSession

REFRESH_MS = 2_000
DRAIN_MS = 50


class ConsoleCoordinator(QObject):
    """
    Coordinador del modulo Consola.

    Responsabilidades
    -----------------
    1. Mirar cada pocos segundos que equipos emparejados estan en la red.
    2. Correr un comando en el elegido y pasar la salida en vivo a la pantalla,
       sin la marca con la carpeta en que quedo.
    3. Pedir la contrasena si el comando lleva sudo y mandarla por stdin; no
       se guarda aqui ni pasa por una senal.
    4. Cancelar el comando: se cierra el canal y el otro equipo lo termina.

    El enlace es el de la ventana: lo abre y lo cierra Emparejar.

    La salida llega en el hilo del bucle y se deja en una cola (deque, segura
    entre hilos); un temporizador de Qt la vacia cada DRAIN_MS, para que un
    comando que escribe mucho no llene la cola de eventos de Qt.

    SENALES
    -------
    view_changed(dict)  -> ConsoleLogic.view(): estado, equipos, carpeta, resultado
    output_added(str)   -> texto nuevo de la salida, con el eco '~/carpeta $ comando'
    output_cleared()    -> clear o Ctrl+L: la pantalla vacia la salida
    """

    view_changed = Signal(object)
    output_added = Signal(str)
    output_cleared = Signal()

    def __init__(
        self,
        loop: AsyncLoop,
        link: LinkSession,
        clock: Callable[[], float] = time.monotonic,
        refresh_every_ms: int = REFRESH_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.logic = ConsoleLogic()
        self._link = link
        self._clock = clock
        self._gen = 0  # sube con cada comando: lo de uno anterior se descarta
        self._future: concurrent.futures.Future | None = None
        self._pending: deque[tuple[int, str, bytes]] = deque()
        self._decoder = OutputDecoder()
        self._marks = ShellMarkFilter()
        self._line_open = False  # la salida no termino en salto de linea
        self._refreshing = False

        self._worker = LinkWorker(loop, self)
        self._worker.finished.connect(self._on_finished)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(refresh_every_ms)
        self._refresh_timer.timeout.connect(self.refresh)
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(DRAIN_MS)
        self._drain_timer.timeout.connect(self._drain)

    @classmethod
    def for_app(
        cls, loop: AsyncLoop, link: LinkSession, parent: QObject | None = None
    ) -> ConsoleCoordinator:
        return cls(loop, link, parent=parent)

    # -- API publica -------------------------------------------

    def start(self) -> None:
        """Empieza a mirar los equipos; la UI lo llama al abrirse."""
        self.refresh()
        self._refresh_timer.start()

    def refresh(self) -> None:
        if not self._refreshing:
            self._refreshing = True
            self._worker.run("reachable", self._gen, self._link.reachable())

    def choose(self, name: str) -> None:
        self.logic.choose(name)
        self._emit_view()

    def run(self, command: str) -> None:
        prompt = self.logic.prompt
        payload = self.logic.start_run(command, self._clock())
        if not payload["ok"]:
            self._emit_view()
            return
        if payload.get("clear"):
            self.clear()
            return
        self._emit_output(("\n" if self._line_open else "") + f"{prompt} $ {payload['command']}\n")
        if payload["asking"]:
            self._emit_view()  # la pantalla pide la contrasena
            return
        self._start(payload)

    def clear(self) -> None:
        """Vacia la salida en la pantalla; no manda nada al otro equipo."""
        self._line_open = False
        self.output_cleared.emit()
        self._emit_view()

    def give_password(self, password: str) -> None:
        payload = self.logic.give_password(password, self._clock())
        if payload["ok"]:
            self._start(payload)
        else:
            self._emit_view()

    def history_older(self, current: str) -> str:
        return self.logic.history.older(current)

    def history_newer(self) -> str:
        return self.logic.history.newer()

    def cancel(self) -> None:
        running = self.logic.is_running
        if not self.logic.cancel(self._clock()):
            return
        if running:
            self._drain()  # lo que ya llego se muestra
            self._end_output()
            self._gen += 1
            future, self._future = self._future, None
            if future is not None:
                future.cancel()
        self._emit_view()

    def view(self) -> dict:
        return self.logic.view()

    def close(self) -> None:
        """Para los temporizadores y cancela el comando; la UI lo llama en su closeEvent."""
        self._refresh_timer.stop()
        self.cancel()
        self._drain_timer.stop()

    # -- Handlers ----------------------------------------------

    def _on_finished(self, result: object) -> None:
        if not isinstance(result, dict) or result["cancelled"]:
            return
        if result["kind"] == "reachable":
            self._refreshing = False
            if result["ok"]:
                self.logic.set_targets([(peer.name, peer.address) for peer in result["value"]])
        elif result["kind"] == "run":
            if result["gen"] != self._gen:
                return  # de un comando cancelado
            self._future = None
            self._drain()
            place = self._end_output()
            self.logic.run_finished(
                result["ok"],
                result["value"],
                self._clock(),
                result["message"],
                result["hint"],
                place,
            )
        self._emit_view()

    # -- Helpers -----------------------------------------------

    def _start(self, payload: dict) -> None:
        self._gen += 1
        gen = self._gen
        self._decoder = OutputDecoder()
        self._marks = ShellMarkFilter()

        def on_output(stream: str, data: bytes) -> None:
            self._pending.append((gen, stream, data))  # hilo del bucle

        coro = self._link.run(payload["target"], payload["script"], on_output, payload["stdin"])
        self._future = self._worker.run("run", gen, coro)
        self._drain_timer.start()
        self._emit_view()

    def _drain(self) -> None:
        parts = []
        while self._pending:
            gen, stream, data = self._pending.popleft()
            if gen == self._gen:
                parts.append(self._decoder.feed(stream, self._marks.feed(stream, data)))
        self._emit_output("".join(parts))

    def _end_output(self) -> Place | None:
        """Muestra lo retenido y devuelve la carpeta en que quedo el comando."""
        self._drain_timer.stop()
        rest, place = self._marks.finish()
        self._emit_output(self._decoder.feed(STDERR, rest) + self._decoder.flush())
        return place

    def _emit_output(self, text: str) -> None:
        if text:
            self._line_open = not text.endswith("\n")
            self.output_added.emit(text)

    def _emit_view(self) -> None:
        self.view_changed.emit(self.view())
