from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from core.async_loop import STOP_TIMEOUT_S, AsyncLoop
from core.link_worker import LinkWorker
from logic._00_logic_pairing import normalize_code
from modules.mod_02_pair.logic._02_logic_pair import LinkState, PairLogic
from services.service_link import BROWSE_S, LinkSession

logger = logging.getLogger(__name__)

BROWSE_EVERY_MS = 5_000
TICK_MS = 1_000
# Cada cuanto se mira si la IP de este equipo cambio, y se repinta la cuenta atras.
WATCH_MS = 1_000
# Tras un error (al abrir o por un corte de red) se reintenta solo a los RETRY_S.
RETRY_S = 5.0


async def _start_link(link: LinkSession, host: str) -> tuple[list[str], int]:
    # El enlace anterior se cierra aqui, en el bucle de red: el hilo de Qt no espera.
    await link.close()
    await link.start(host)
    return link.paired_names(), link.ssh_port


class PairCoordinator(QObject):
    """
    Coordinador del modulo Emparejar.

    Responsabilidades
    -----------------
    1. Abrir el enlace (servidor y anuncio) al empezar y cerrarlo al salir. El
       enlace lo crea la ventana y lo comparte con la consola.
    2. Buscar equipos cada pocos segundos mientras esta en la red.
    3. Emparejar en los dos sentidos: escribir el codigo de otro o mostrar el propio.
    4. Pasar cada resultado por la maquina de estados y emitir la vista.
    5. Vigilar la IP de este equipo: si cambia o se va, cerrar el enlace y
       reintentar solo cada RETRY_S hasta que vuelva la red.

    SENALES
    -------
    view_changed(dict)                -> PairLogic.view(): estado, filas, ventana del codigo
    connection_changed(ConnectionLine) -> la linea de estado del pie de la ventana
    """

    view_changed = Signal(object)
    connection_changed = Signal(object)

    def __init__(
        self,
        loop: AsyncLoop,
        link: LinkSession,
        host_fn: Callable[[], str],
        clock: Callable[[], float] = time.monotonic,
        browse_every_ms: int = BROWSE_EVERY_MS,
        watch_ms: int = WATCH_MS,
        retry_s: float = RETRY_S,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.logic = PairLogic()
        self._link = link
        self._host_fn = host_fn
        self._clock = clock
        self._started = False
        self._gen = 0
        self._browsing = False
        self._retry_s = retry_s

        self._worker = LinkWorker(loop, self)
        self._worker.finished.connect(self._on_finished)
        self._browse_timer = QTimer(self)
        self._browse_timer.setInterval(browse_every_ms)
        self._browse_timer.timeout.connect(self._browse)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(TICK_MS)
        self._tick_timer.timeout.connect(self._emit_view)
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(watch_ms)
        self._watch_timer.timeout.connect(self._watch)
        self._handlers = {
            "start": self._on_started,
            "browse": self._on_browsed,
            "join": self._on_joined,
            "open_window": self._on_window_opened,
            "wait_window": self._on_window_finished,
            "forget": self._on_forgotten,
        }

    @classmethod
    def for_app(
        cls, loop: AsyncLoop, link: LinkSession, parent: QObject | None = None
    ) -> PairCoordinator:
        """El de la app: el enlace de la ventana en la IP de la ruta por defecto."""
        from services.service_probe import default_host

        return cls(loop, link, default_host, parent=parent)

    # -- API publica -------------------------------------------

    def start(self) -> None:
        """Abre el enlace en la IP de la red local; tambien sirve para reintentar."""
        self._stop_timers()
        host = self._host_fn()
        self.logic.link_starting(host)
        self._gen += 1
        self._started = True
        self._run("start", _start_link(self._link, host))
        self._watch_timer.start()
        self._emit_view()

    def join(self, name: str, code: str) -> None:
        """Escribe el codigo que muestra el equipo name."""
        payload = self.logic.start_join(name, code)
        if payload["ok"]:
            code = normalize_code(code)
            self._run("join", self._link.join(code, payload["address"]), name=name)
        self._emit_view()

    def open_window(self) -> None:
        if self.logic.is_online and not self.logic.window_open:
            self._run("open_window", self._link.open_window())

    def close_window(self) -> None:
        self._run("close_window", self._link.close_window())

    def forget(self, name: str) -> None:
        self._run("forget", self._link.forget(name), name=name)

    def view(self) -> dict:
        return self.logic.view(self._clock())

    def connection(self):
        return self.logic.connection(self._clock())

    def close(self) -> None:
        """Cierra puertos y temporizadores; la UI lo llama en su closeEvent."""
        self._close_link()

    # -- Handlers ----------------------------------------------

    def _on_finished(self, result: object) -> None:
        if not isinstance(result, dict) or result["gen"] != self._gen or result["cancelled"]:
            return  # de un enlace anterior o cancelado al cerrar
        handler = self._handlers.get(result["kind"])
        if handler is not None:
            handler(result)
        self._emit_view()

    def _on_started(self, result: dict) -> None:
        if not result["ok"]:
            self.logic.link_failed(result["message"], result["hint"])
            self.logic.schedule_retry(self._clock(), self._retry_s)
            return
        names, port = result["value"]
        self.logic.set_paired(names)
        self.logic.link_started(port)
        self._browse()
        self._browse_timer.start()

    def _on_browsed(self, result: dict) -> None:
        self._browsing = False
        if result["ok"]:
            self.logic.peers_found([(peer.name, peer.address) for peer in result["value"]])

    def _on_joined(self, result: dict) -> None:
        name = result["extra"]["name"]
        self.logic.join_finished(name, result["ok"], result["message"], result["hint"])

    def _on_window_opened(self, result: dict) -> None:
        if not result["ok"]:
            self.logic.window_failed(result["message"], result["hint"])
            return
        info = result["value"]
        self.logic.window_opened(info.code, info.port, info.seconds, self._clock())
        self._tick_timer.start()
        self._run("wait_window", self._link.wait_window())

    def _on_window_finished(self, result: dict) -> None:
        self._tick_timer.stop()
        peer, why = result["value"] if result["ok"] else (None, "CLOSED")
        self.logic.window_finished(why, peer.name if peer is not None else "")

    def _on_forgotten(self, result: dict) -> None:
        if result["ok"] and result["value"]:
            self.logic.forgotten(result["extra"]["name"])

    def _watch(self) -> None:
        if self.logic.is_online:
            if self._host_fn() != self.logic.host:
                self._lose_link()
        elif self.logic.state is LinkState.ERROR and self.logic.retry_in(self._clock()) == 0:
            self.start()
            return
        self.connection_changed.emit(self.connection())

    def _lose_link(self) -> None:
        """Cambio la IP o se fue la red: cierra el enlace sin esperar y cuenta atras."""
        self._stop_timers()
        self._watch_timer.start()
        self._gen += 1  # lo que llegue del enlace viejo se descarta
        self._run("close", self._link.close())
        self.logic.link_lost()
        self.logic.schedule_retry(self._clock(), self._retry_s)
        self._emit_view()

    # -- Helpers -----------------------------------------------

    def _browse(self) -> None:
        if self.logic.is_online and not self._browsing:
            self._browsing = True
            self._run("browse", self._link.browse(BROWSE_S))

    def _run(self, kind: str, coro, **extra) -> None:
        self._worker.run(kind, self._gen, coro, **extra)

    def _emit_view(self) -> None:
        self.view_changed.emit(self.view())
        self.connection_changed.emit(self.connection())

    def _stop_timers(self) -> None:
        self._browse_timer.stop()
        self._tick_timer.stop()
        self._watch_timer.stop()
        self._browsing = False

    def _close_link(self) -> None:
        self._stop_timers()
        self._gen += 1  # lo que llegue del enlace anterior se descarta
        if not self._started:
            return
        self._started = False
        try:
            self._worker.run_blocking(self._link.close(), STOP_TIMEOUT_S)
        except Exception:  # noqa: BLE001 (al cerrar se sigue aunque falle)
            logger.exception("No se pudo cerrar el enlace")
