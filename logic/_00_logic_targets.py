"""Lo comun de los modulos que usan la red: a que equipo se habla y como se dice el resultado.

Consola, Archivos y Chat eligen un equipo entre los emparejados que estan en
la red y muestran una linea con lo que paso, con tiempos y tamanos. Logica pura, sin PySide6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_UNITS = ("B", "KB", "MB", "GB", "TB")


class Tone(StrEnum):
    NEUTRAL = "neutral"
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Outcome:
    """Una linea para el usuario: que paso y, si fallo, que hacer."""

    text: str
    tone: Tone
    hint: str = ""


NO_TARGET = Outcome(
    "Ningún equipo emparejado está en la red.",
    Tone.NEUTRAL,
    "Empareja uno en 'Emparejar' o abre Molink en el otro equipo.",
)


def seconds_text(elapsed: float) -> str:
    """2.345 -> '2,3 s'; nunca negativo."""
    return f"{max(elapsed, 0.0):.1f} s".replace(".", ",")


def human_size(size: float) -> str:
    """1536 -> '1,5 KB'; con coma decimal como el resto de la app."""
    unit = 0
    while size >= 1024 and unit < len(_UNITS) - 1:
        size /= 1024
        unit += 1
    text = f"{size:.0f}" if unit == 0 else f"{size:.1f}"
    return f"{text} {_UNITS[unit]}".replace(".", ",")


class TargetChoice:
    """
    Equipo elegido entre los alcanzables (nombre, IP).

    REGLAS
    - Si el elegido sale de la red, se pasa al primero que quede ("" si ninguno).
    - Mientras busy es True (un comando corre, un archivo va) no se cambia de
      equipo; la lista se guarda y se aplica al terminar con _settle().
    - Cada modulo pone su estado en _settle() a partir de self.target.
    """

    def __init__(self) -> None:
        self.targets: list[tuple[str, str]] = []
        self.target = ""

    @property
    def busy(self) -> bool:
        return False

    def set_targets(self, targets: list[tuple[str, str]]) -> None:
        self.targets = list(targets)
        if not self.busy:
            self._settle()

    def choose(self, name: str) -> bool:
        if self.busy or name not in self._names():
            return False
        self.target = name
        return True

    @property
    def address(self) -> str:
        return dict(self.targets).get(self.target, "")

    def _names(self) -> list[str]:
        return [name for name, _ in self.targets]

    def _settle(self) -> None:
        names = self._names()
        if self.target not in names:
            self.target = names[0] if names else ""
