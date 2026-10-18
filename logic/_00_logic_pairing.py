"""Ventana de emparejamiento: codigo de 6 digitos, 2 minutos y pocos intentos.

Logica pura: el reloj llega como argumento (time.monotonic en la app), asi
las pruebas avanzan el tiempo sin esperar. El codigo no se guarda aqui.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from enum import StrEnum

CODE_DIGITS = 6
WINDOW_SECONDS = 120.0
MAX_ATTEMPTS = 3


class PairingState(StrEnum):
    OPEN = "OPEN"  # esperando a que el otro equipo escriba el codigo
    PAIRED = "PAIRED"  # un intento salio bien; el codigo ya no sirve
    EXPIRED = "EXPIRED"  # pasaron los 2 minutos
    LOCKED = "LOCKED"  # se gastaron los intentos
    CLOSED = "CLOSED"  # el usuario cancelo


def new_code(randbelow: Callable[[int], int] = secrets.randbelow) -> str:
    """Codigo al azar criptografico de 6 digitos, con ceros a la izquierda."""
    return f"{randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def normalize_code(text: str) -> str:
    """Acepta '123 456' o '123-456'; exige exactamente 6 digitos."""
    code = "".join(ch for ch in text if ch not in " -")
    if len(code) != CODE_DIGITS or not code.isascii() or not code.isdigit():
        raise ValueError("El codigo tiene 6 digitos")
    return code


class PairingWindow:
    """Estado del lado que muestra el codigo.

    Un intento se descuenta al empezar, no al fallar: asi nadie abre varios
    a la vez para probar mas codigos de los permitidos.
    """

    def __init__(
        self, now: float, window: float = WINDOW_SECONDS, max_attempts: int = MAX_ATTEMPTS
    ):
        self._deadline = now + window
        self._attempts_left = max_attempts
        self._final: PairingState | None = None

    @property
    def attempts_left(self) -> int:
        return self._attempts_left

    def state(self, now: float) -> PairingState:
        if self._final is not None:
            return self._final
        if now >= self._deadline:
            return PairingState.EXPIRED
        if self._attempts_left <= 0:
            return PairingState.LOCKED
        return PairingState.OPEN

    def remaining(self, now: float) -> float:
        """Segundos que le quedan a la ventana (0 si ya no esta abierta)."""
        if self.state(now) is not PairingState.OPEN:
            return 0.0
        return self._deadline - now

    def start_attempt(self, now: float) -> PairingState:
        """Descuenta un intento si la ventana esta abierta; devuelve el estado previo."""
        state = self.state(now)
        if state is PairingState.OPEN:
            self._attempts_left -= 1
        return state

    def finish_attempt(self, now: float, success: bool) -> PairingState:
        """Cierra un intento: si salio bien dentro del plazo, queda emparejado."""
        if success and self._final is None and now < self._deadline:
            self._final = PairingState.PAIRED
        return self.state(now)

    def close(self) -> None:
        if self._final is None:
            self._final = PairingState.CLOSED
