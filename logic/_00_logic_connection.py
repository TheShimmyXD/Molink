"""La linea de estado de la conexion, al pie de la ventana.

Un solo lugar para saber si Molink esta en la red y con quien: abriendo, sin
equipo emparejado, buscando, conectado o el error con su cuenta atras.
Logica pura, sin PySide6: recibe el estado del enlace y devuelve que pintar.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from logic._00_logic_targets import Tone

# Valores de LinkState (modulo Emparejar); aqui como texto para no depender de el.
STARTING = "STARTING"
ONLINE = "ONLINE"
ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ConnectionLine:
    """Lo que pinta la linea: punto y texto, la direccion propia y si se puede reintentar."""

    text: str
    tone: Tone
    address: str = ""  # IP:puerto de este equipo; vacio fuera de la red
    hint: str = ""  # va en la ayuda (tooltip)
    can_retry: bool = False


def _names(names: list[str]) -> str:
    """['a'] -> 'a'; ['a', 'b', 'c'] -> 'a, b y c'."""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} y {names[-1]}"


def connection_line(
    state: str,
    host: str,
    port: int,
    paired: Iterable[str],
    seen: Iterable[str],
    error: tuple[str, str] = ("", ""),
    retry_in: int = 0,
) -> ConnectionLine:
    """
    REGLAS
    - Conectado = emparejado y visto en la red hace poco (lo mismo que usan
      Consola y Chat para elegir equipo).
    - En ERROR siempre se puede reintentar; con retry_in > 0 se dice cuando
      se reintenta solo.
    """
    if state == STARTING:
        return ConnectionLine(f"Abriendo Molink en {host or 'la red'}...", Tone.WARNING)
    if state == ERROR:
        message, hint = error
        text = message.rstrip(".") or "Molink no está en la red"
        text = (
            f"{text}, reintentando en {retry_in} s" if retry_in > 0 else f"{text}, reintentando..."
        )
        return ConnectionLine(text, Tone.ERROR, hint=hint, can_retry=True)
    address = f"{host}:{port}" if port else host
    paired = sorted(paired)
    if not paired:
        return ConnectionLine(
            "Sin equipo emparejado",
            Tone.NEUTRAL,
            address,
            "Empareja uno en 'Emparejar'.",
        )
    reachable = [name for name in paired if name in set(seen)]
    if not reachable:
        return ConnectionLine(
            f"Buscando a {_names(paired)}...",
            Tone.WARNING,
            address,
            "Abre Molink en el otro equipo; se busca solo.",
        )
    return ConnectionLine(f"Conectado a {_names(reachable)}", Tone.OK, address)
