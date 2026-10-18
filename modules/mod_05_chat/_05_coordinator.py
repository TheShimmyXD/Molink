from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from core.async_loop import AsyncLoop
from core.link_worker import LinkWorker
from modules.mod_05_chat.logic._05_logic_chat import ChatLogic
from services.service_chat import ChatMessage
from services.service_link import LinkSession
from services.service_transfer import IncomingEvent, ensure_inbox

REFRESH_MS = 2_000
PROGRESS_MS = 100


class ChatCoordinator(QObject):
    """
    Coordinador del modulo Chat.

    Responsabilidades
    -----------------
    1. Mirar cada pocos segundos que equipos emparejados estan en la red.
    2. Enviar mensajes (en paralelo) y archivos (de uno en uno) al equipo elegido.
    3. Recibir los mensajes y los avisos de archivos que llegan por el enlace.

    Lo crea la ventana al arrancar, no al abrir la pantalla: lo que llega se
    guarda aunque nadie mire y el boton Chat muestra el punto (badge_changed).
    Se suscribe a on_message y on_incoming del enlace; esos llegan en el hilo
    del bucle y cruzan a Qt por la senal interna _arrived (conexion en cola).
    El avance de un envio se guarda como ultimo valor y se lee cada PROGRESS_MS.

    SENALES
    -------
    view_changed(dict)   -> ChatLogic.view()
    badge_changed(dict)  -> ChatLogic.badge(): unread, busy, tooltip
    """

    view_changed = Signal(object)
    badge_changed = Signal(object)
    _arrived = Signal(object)  # ChatMessage o IncomingEvent desde el hilo del bucle

    def __init__(
        self,
        loop: AsyncLoop,
        link: LinkSession,
        clock: Callable[[], float] = time.time,
        refresh_every_ms: int = REFRESH_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.logic = ChatLogic()
        self._link = link
        self._clock = clock
        self._gen = 0  # sube con cada archivo: lo de uno cancelado se descarta
        self._future: concurrent.futures.Future | None = None
        self._latest: tuple[int, int] | None = None  # (gen, enviados) del hilo del bucle
        self._refreshing = False
        self._last_badge: dict | None = None

        self._worker = LinkWorker(loop, self)
        self._worker.finished.connect(self._on_finished)
        self._arrived.connect(self._on_arrived)
        self._hop = self._arrived.emit
        link.on_message = self._hop
        link.on_incoming = self._hop
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(refresh_every_ms)
        self._refresh_timer.timeout.connect(self.refresh)
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(PROGRESS_MS)
        self._progress_timer.timeout.connect(self._show_progress)

    @classmethod
    def for_app(
        cls, loop: AsyncLoop, link: LinkSession, parent: QObject | None = None
    ) -> ChatCoordinator:
        return cls(loop, link, parent=parent)

    # -- API publica -------------------------------------------

    def start(self) -> None:
        """Empieza a mirar los equipos; la ventana lo llama al crearlo."""
        self.refresh()
        self._refresh_timer.start()

    def refresh(self) -> None:
        if not self._refreshing:
            self._refreshing = True
            self._worker.run("reachable", 0, self._link.reachable())

    def set_visible(self, visible: bool) -> None:
        """La pantalla avisa si se esta viendo: lo que llega entonces ya esta leido."""
        self.logic.set_visible(visible)
        self._emit_view()

    def choose(self, name: str) -> None:
        self.logic.choose(name)
        self._emit_view()

    def write(self, text: str) -> bool:
        """Envia un mensaje; False si no se pudo (sin equipo o vacio)."""
        payload = self.logic.write(text, self._clock())
        if payload["ok"]:
            coro = self._link.say(payload["target"], payload["text"])
            self._worker.run("say", 0, coro, entry_id=payload["entry_id"])
        self._emit_view()
        return payload["ok"]

    def send(self, paths: list[Path]) -> None:
        """Pone en cola los archivos soltados o elegidos con el clip; las carpetas se omiten."""
        files, skipped = [], 0
        for path in paths:
            if path.is_file():
                files.append((path, path.stat().st_size))
            else:
                skipped += 1
        self.logic.add_files(files, skipped, self._clock())
        self._start_next()
        self._emit_view()

    def cancel(self, entry_id: int) -> None:
        """Cancela un archivo que sale: el que va en camino o uno de la cola."""
        if self.logic.cancel_file(entry_id) == "current":
            self._progress_timer.stop()
            self._gen += 1
            future, self._future = self._future, None
            if future is not None:
                future.cancel()
            self._start_next()
        self._emit_view()

    def open_inbox(self) -> str:
        """Ruta de la carpeta de llegada, creada si aun no existe ("" si no hay)."""
        inbox = self._link.settings.inbox
        return str(ensure_inbox(inbox)) if inbox is not None else ""

    def view(self) -> dict:
        return self.logic.view()

    def close(self) -> None:
        """Para los temporizadores, cancela el envio y suelta el enlace."""
        self._refresh_timer.stop()
        self._progress_timer.stop()
        future, self._future = self._future, None
        if future is not None:
            future.cancel()
        if self._link.on_message is self._hop:
            self._link.on_message = None
        if self._link.on_incoming is self._hop:
            self._link.on_incoming = None

    # -- Handlers ----------------------------------------------

    def _on_arrived(self, item: object) -> None:
        if isinstance(item, ChatMessage):
            self.logic.received(item.peer, item.message_id, item.text, item.received_at)
        elif isinstance(item, IncomingEvent):
            self.logic.incoming(
                item.peer,
                item.transfer_id,
                item.kind.name,
                item.name,
                item.received,
                item.total or 0,
                self._clock(),
            )
        self._emit_view()

    def _on_finished(self, result: object) -> None:
        if not isinstance(result, dict) or result["cancelled"]:
            return
        kind = result["kind"]
        if kind == "reachable":
            self._refreshing = False
            if result["ok"]:
                self.logic.set_targets([(peer.name, peer.address) for peer in result["value"]])
        elif kind == "say":
            entry_id = result["extra"]["entry_id"]
            self.logic.text_finished(entry_id, result["ok"], result["message"], result["hint"])
        elif kind == "send":
            if result["gen"] != self._gen:
                return  # de un envio cancelado
            self._future = None
            self._progress_timer.stop()
            more = self.logic.file_finished(
                result["extra"]["entry_id"],
                result["ok"],
                result["value"] or "",
                result["message"],
                result["hint"],
            )
            if more:
                self._start_next()
        self._emit_view()

    # -- Helpers -----------------------------------------------

    def _start_next(self) -> None:
        payload = self.logic.start_next_file()
        if not payload["ok"]:
            return
        self._gen += 1
        gen = self._gen
        self._latest = None

        def on_progress(sent: int, _total: int) -> None:
            self._latest = (gen, sent)  # hilo del bucle

        coro = self._link.send(payload["target"], payload["path"], on_progress)
        self._future = self._worker.run("send", gen, coro, entry_id=payload["entry_id"])
        self._progress_timer.start()

    def _show_progress(self) -> None:
        latest = self._latest
        entry_id = self.logic.sending_file
        if latest is not None and latest[0] == self._gen and entry_id is not None:
            self.logic.file_progress(entry_id, latest[1])
            self._emit_view()

    def _emit_view(self) -> None:
        self.view_changed.emit(self.view())
        badge = self.logic.badge()
        if badge != self._last_badge:
            self._last_badge = badge
            self.badge_changed.emit(badge)
