"""Estados de la pantalla de emparejar: enlace, equipos, ventana del codigo.

Logica pura: el reloj llega como argumento y la red la maneja el coordinador.
El codigo propio vive aqui solo mientras la ventana esta abierta, para
mostrarlo; nunca sale en el texto de estado ni en un log.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from logic._00_logic_connection import ConnectionLine, connection_line
from logic._00_logic_pairing import normalize_code


class LinkState(StrEnum):
    STARTING = "STARTING"  # abriendo servidor y anuncio
    ONLINE = "ONLINE"  # en la red: buscando y visible para los otros
    ERROR = "ERROR"  # no se pudo abrir o se corto la red; se reintenta solo


class Tone(StrEnum):
    NEUTRAL = "neutral"
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class PeerRow:
    """Un equipo en la lista: visto en la red, emparejado o las dos cosas."""

    name: str
    address: str  # '' si esta emparejado pero no aparece en la red
    paired: bool
    joining: bool = False
    error: str = ""


@dataclass(frozen=True, slots=True)
class Status:
    text: str
    hint: str = ""
    tone: Tone = Tone.NEUTRAL
    busy: bool = False  # buscando o emparejando: la UI muestra el icono de actividad


LOST_TEXT = ("Se cortó la red.", "Molink se vuelve a abrir solo cuando haya red.")

WINDOW_END_TEXTS = {
    "EXPIRED": ("Se acabó el tiempo del código.", "Pulsa 'Mostrar mi código' para otro."),
    "LOCKED": (
        "Se gastaron los intentos del código.",
        "Revisa que allá escriban este código y pide otro.",
    ),
}


class PairLogic:
    """
    MAQUINA DE ESTADOS - MODULO EMPAREJAR

    STARTING -> link_started()          -> ONLINE
    STARTING -> link_failed(msg, hint)  -> ERROR
    ONLINE   -> link_lost()             -> ERROR     (se corto la red)
    ERROR    -> link_starting(host)     -> STARTING  (reintentar)

    En ERROR, schedule_retry(now, s) fija cuando se reintenta solo; retry_in(now)
    da los segundos que faltan (el coordinador reintenta al llegar a 0).

    En ONLINE, sin cambiar de estado:
        peers_found(peers)        actualiza los equipos vistos
        start_join(name, code)    -> join_finished(name, ok, ...)  (uno a la vez)
        window_opened(code, ...)  -> window_finished(state, peer)  (ventana del codigo)
        forgotten(name)           quita un emparejado

    REGLAS
    - Sin PySide6 ni red: solo estado y textos.
    - Un solo emparejado en curso; el codigo se valida antes de gastar un intento.
    """

    def __init__(self) -> None:
        self.state = LinkState.STARTING
        self.host = ""
        self._error = ("", "")
        self._seen: dict[str, str] = {}
        self._searched = False
        self._paired: set[str] = set()
        self._joining = ""
        self._row_errors: dict[str, str] = {}
        self._notice: tuple[str, Tone] = ("", Tone.NEUTRAL)
        self._code = ""
        self._window_port = 0
        self._deadline = 0.0
        self._port = 0
        self._retry_at = 0.0

    @property
    def is_online(self) -> bool:
        return self.state is LinkState.ONLINE

    @property
    def window_open(self) -> bool:
        return bool(self._code)

    # -- Enlace ------------------------------------------------

    def link_starting(self, host: str) -> dict:
        self.state = LinkState.STARTING
        self.host = host
        self._error = ("", "")
        self._searched = False
        self._retry_at = 0.0
        return self._payload(True)

    def link_started(self, port: int = 0) -> dict:
        if self.state is not LinkState.STARTING:
            return self._payload(False, "El enlace no se estaba abriendo.")
        self.state = LinkState.ONLINE
        self._port = port
        return self._payload(True)

    def link_failed(self, message: str, hint: str = "") -> dict:
        self.state = LinkState.ERROR
        self._error = (message, hint)
        self._seen.clear()
        self._joining = ""
        self._code = ""
        self._port = 0
        return self._payload(False, message)

    def link_lost(self) -> dict:
        """La IP de este equipo cambio o se fue: el enlace ya no sirve."""
        if not self.is_online:
            return self._payload(False, "El enlace no estaba en la red.")
        return self.link_failed(*LOST_TEXT)

    def schedule_retry(self, now: float, seconds: float) -> dict:
        if self.state is not LinkState.ERROR:
            return self._payload(False, "Solo se reintenta tras un error.")
        self._retry_at = now + seconds
        return self._payload(True)

    def retry_in(self, now: float) -> int:
        """Segundos enteros hasta el reintento solo; 0 si ya toca o no hay ninguno."""
        if self.state is not LinkState.ERROR or not self._retry_at:
            return 0
        return max(0, int(self._retry_at - now + 0.999))

    # -- Equipos -----------------------------------------------

    def set_paired(self, names: list[str]) -> dict:
        self._paired = set(names)
        return self._payload(True)

    def peers_found(self, peers: list[tuple[str, str]]) -> dict:
        """peers: (nombre, IP) de cada equipo con Molink abierto en la red."""
        if not self.is_online:
            return self._payload(False, "Fuera de la red.")
        self._seen = dict(peers)
        self._searched = True
        return self._payload(True)

    def start_join(self, name: str, code: str) -> dict:
        """Valida antes de conectar; ok con la IP del equipo para el coordinador."""
        if not self.is_online:
            return self._payload(False, "Molink no está en la red.")
        if self._joining:
            return self._payload(False, f"Ya se está emparejando con {self._joining}.")
        if name not in self._seen:
            return self._payload(False, f"{name} ya no aparece en la red.")
        if name in self._paired:
            return self._payload(False, f"{name} ya está emparejado.")
        try:
            normalize_code(code)
        except ValueError:
            self._row_errors[name] = "El código tiene 6 dígitos."
            return self._payload(False, self._row_errors[name])
        self._joining = name
        self._row_errors.pop(name, None)
        self._notice = ("", Tone.NEUTRAL)
        payload = self._payload(True)
        payload["address"] = self._seen[name]
        return payload

    def join_finished(self, name: str, ok: bool, message: str = "", hint: str = "") -> dict:
        if name != self._joining:
            return self._payload(False, "No se estaba emparejando con ese equipo.")
        self._joining = ""
        if ok:
            self._paired.add(name)
            self._notice = (f"Emparejado con {name}.", Tone.OK)
            return self._payload(True)
        self._row_errors[name] = " ".join(part for part in (message, hint) if part)
        return self._payload(False, message)

    def forgotten(self, name: str) -> dict:
        self._paired.discard(name)
        self._notice = (f"{name} olvidado: ya no puede entrar.", Tone.NEUTRAL)
        return self._payload(True)

    # -- Ventana del codigo -------------------------------------

    def window_opened(self, code: str, port: int, seconds: float, now: float) -> dict:
        self._code = code
        self._window_port = port
        self._deadline = now + seconds
        self._notice = ("", Tone.NEUTRAL)
        return self._payload(True)

    def window_finished(self, state: str, peer_name: str = "") -> dict:
        """Termino la ventana: PAIRED con peer_name, EXPIRED, LOCKED o CLOSED."""
        self._code = ""
        self._window_port = 0
        if peer_name:
            self._paired.add(peer_name)
            self._notice = (f"Emparejado con {peer_name}.", Tone.OK)
        elif state in WINDOW_END_TEXTS:
            text, hint = WINDOW_END_TEXTS[state]
            self._notice = (f"{text} {hint}", Tone.ERROR)
        return self._payload(True)

    def window_failed(self, message: str, hint: str = "") -> dict:
        self._code = ""
        self._notice = (" ".join(part for part in (message, hint) if part), Tone.ERROR)
        return self._payload(False, message)

    def remaining(self, now: float) -> int:
        """Segundos enteros que le quedan a la ventana (0 si esta cerrada)."""
        if not self._code:
            return 0
        return max(0, int(self._deadline - now + 0.999))

    # -- Lo que muestra la UI ----------------------------------

    def rows(self) -> list[PeerRow]:
        """Primero los vistos en la red, luego los emparejados ausentes; por nombre."""
        names = sorted(self._seen) + sorted(self._paired - set(self._seen))
        return [
            PeerRow(
                name=name,
                address=self._seen.get(name, ""),
                paired=name in self._paired,
                joining=name == self._joining,
                error=self._row_errors.get(name, ""),
            )
            for name in names
        ]

    def status(self) -> Status:
        if self.state is LinkState.STARTING:
            return Status(f"Abriendo Molink en {self.host or 'la red'}...", busy=True)
        if self.state is LinkState.ERROR:
            message, hint = self._error
            return Status(message, hint, Tone.ERROR)
        if self._joining:
            return Status(f"Emparejando con {self._joining}...", busy=True)
        text, tone = self._notice
        if text:
            return Status(text, tone=tone)
        if not self._searched:
            return Status("Buscando equipos en la red...", busy=True)
        count = len(self._seen)
        if count == 0:
            return Status(
                "Nadie más con Molink abierto en la red.",
                "Abre Molink en el otro equipo; se busca solo.",
                busy=True,
            )
        return Status(f"{count} equipo{'s' if count > 1 else ''} en la red.", busy=True)

    def connection(self, now: float) -> ConnectionLine:
        """La linea de estado del pie de la ventana."""
        return connection_line(
            self.state.value,
            self.host,
            self._port,
            self._paired,
            self._seen,
            self._error,
            self.retry_in(now),
        )

    def view(self, now: float) -> dict:
        """Todo lo que la UI pinta, en un solo dict."""
        return {
            "state": self.state.value,
            "host": self.host,
            "status": self.status(),
            "rows": self.rows(),
            "window_open": self.window_open,
            "code": self._code,
            "window_port": self._window_port,
            "remaining": self.remaining(now),
        }

    # -- Helpers -----------------------------------------------

    def _payload(self, ok: bool, message: str = "") -> dict:
        status = self.status()
        return {
            "ok": ok,
            "state": self.state.value,
            "status": status.text,
            "message": message or status.text,
        }
