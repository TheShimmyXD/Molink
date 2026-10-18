"""Bucle asyncio en un hilo propio, junto al de Qt (medido: hueco de Qt 4 veces menor que qasync).

Los servicios de red son asyncio puro; la UI no los espera. Un solo bucle
para toda la app: submit() le pasa una corrutina desde el hilo de Qt y
devuelve un concurrent.futures.Future. Quien lo recibe entrega el resultado
a Qt con una senal, nunca tocando widgets desde aqui.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

STOP_TIMEOUT_S = 5.0
# Cancelar una tarea puede crear otras (asyncssh al cerrar canales): se repite.
CANCEL_ROUNDS = 3


class AsyncLoop:
    """Dueno del hilo y del bucle; stop() cancela lo pendiente y espera al hilo."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="molink-asyncio", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        self._loop.close()

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._loop.is_closed()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> concurrent.futures.Future:
        """Agenda coro en el bucle; el Future se resuelve en el hilo del bucle."""
        if not self.running:
            coro.close()
            raise RuntimeError("El bucle de red ya se cerro")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self, cleanup: Coroutine[Any, Any, Any] | None = None) -> bool:
        """Corre cleanup (cerrar puertos), cancela lo que quede y para el hilo.

        Devuelve True si el hilo termino dentro del plazo.
        """
        if not self.running:
            if cleanup is not None:
                cleanup.close()
            return True
        if cleanup is not None:
            try:
                self.submit(cleanup).result(STOP_TIMEOUT_S)
            except Exception:  # noqa: BLE001 (al cerrar se sigue aunque falle la limpieza)
                logger.exception("Fallo la limpieza del bucle de red")
        self.submit(self._cancel_pending()).result(STOP_TIMEOUT_S)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(STOP_TIMEOUT_S)
        return not self._thread.is_alive()

    async def _cancel_pending(self) -> None:
        current = asyncio.current_task()
        for _ in range(CANCEL_ROUNDS):
            tasks = [task for task in asyncio.all_tasks() if task is not current]
            if not tasks:
                return
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)  # deja arrancar lo que la cancelacion agendo
