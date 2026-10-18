"""Worker del enlace: lo comparten las pantallas que usan la red (emparejar, consola)."""

from __future__ import annotations

import concurrent.futures
import logging
from collections.abc import Coroutine
from typing import Any

from PySide6.QtCore import QObject, Signal

from core.async_loop import AsyncLoop
from services.service_link import LinkError

logger = logging.getLogger(__name__)


class LinkWorker(QObject):
    """
    Puente entre el bucle de red y Qt: corre una corrutina del enlace en el
    bucle asyncio y entrega el resultado con una senal.

    La senal se emite desde el hilo del bucle; como el coordinador vive en el
    hilo de Qt, la conexion queda en cola y el slot corre en el hilo de Qt.

    SENALES
    -------
    finished(dict)
        kind  : str   que operacion era (start, browse, join, run, ...)
        gen   : int   enlace al que pertenece (se descartan los de uno viejo)
        ok    : bool
        value : object  lo que devolvio la corrutina
        message, hint : str  si fallo, que paso y que hacer
        cancelled : bool
        extra : dict  lo que el coordinador quiera recibir de vuelta
    """

    finished = Signal(object)

    def __init__(self, loop: AsyncLoop, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loop = loop

    def run(
        self, kind: str, gen: int, coro: Coroutine[Any, Any, Any], **extra
    ) -> concurrent.futures.Future | None:
        """Agenda coro; el Future devuelto sirve para cancelarla (None si el bucle cerro)."""
        base = {"kind": kind, "gen": gen, "extra": extra}
        try:
            future = self._loop.submit(coro)
        except RuntimeError:
            self.finished.emit({**base, **_failure("El bucle de red está cerrado.")})
            return None
        future.add_done_callback(lambda done: self.finished.emit({**base, **_result(done)}))
        return future

    def run_blocking(self, coro: Coroutine[Any, Any, Any], timeout: float) -> Any:
        """Espera el resultado en el hilo de Qt: solo para cerrar puertos al salir."""
        return self._loop.submit(coro).result(timeout)


def _failure(message: str, hint: str = "", cancelled: bool = False) -> dict:
    return {"ok": False, "value": None, "message": message, "hint": hint, "cancelled": cancelled}


def _result(future: concurrent.futures.Future) -> dict:
    # Frontera del hilo: una excepcion aqui se perderia sin avisar a la UI.
    if future.cancelled():
        return _failure("", cancelled=True)
    exc = future.exception()
    if exc is None:
        return {"ok": True, "value": future.result(), "message": "", "hint": "", "cancelled": False}
    if isinstance(exc, LinkError):
        return _failure(exc.message, exc.hint)
    logger.error("Fallo inesperado en el enlace", exc_info=exc)
    return _failure("Error inesperado en la red.", "Revisa el log y reintenta.")
