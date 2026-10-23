"""Estados de la consola: a que equipo se le corre, el comando en curso y como termino.

Logica pura: el reloj llega como argumento y la red la maneja el coordinador.
La salida del comando solo pasa por aqui para volverla texto (OutputDecoder);
nunca entra al texto de estado ni a un log. La contrasena de sudo tampoco se
guarda: give_password la convierte en stdin y la suelta.
"""

from __future__ import annotations

import codecs
from enum import StrEnum

from logic._00_logic_platform import OS_LINUX
from logic._00_logic_targets import NO_TARGET, Outcome, TargetChoice, Tone, seconds_text
from modules.mod_03_console.logic._03_logic_shell import (
    CommandHistory,
    Place,
    is_clear,
    needs_password,
    short_path,
    wrap_command,
)

ENCODING = "utf-8"


class ConsoleState(StrEnum):
    NO_TARGET = "NO_TARGET"  # ningun equipo emparejado esta en la red
    READY = "READY"  # hay equipo: se puede correr un comando
    ASKING = "ASKING"  # el comando lleva sudo: falta la contrasena
    RUNNING = "RUNNING"  # un comando corre alla


class ConsoleLogic(TargetChoice):
    """
    MAQUINA DE ESTADOS - MODULO CONSOLE

    NO_TARGET
        -> set_targets([...])          -> READY

    READY
        -> set_targets([])             -> NO_TARGET
        -> start_run(comando)          -> RUNNING
        -> start_run(comando con sudo) -> ASKING
        -> start_run("clear")          -> READY (la salida se limpia aqui)

    ASKING
        -> give_password(contrasena)   -> RUNNING
        -> cancel()                    -> READY o NO_TARGET

    RUNNING
        -> run_finished(...)           -> READY o NO_TARGET
        -> cancel()                    -> READY o NO_TARGET

    REGLAS
    - Sin PySide6 ni I/O; el reloj llega como argumento.
    - Mientras corre o pide contrasena no se cambia de equipo: el elegido se
      queda aunque desaparezca de la busqueda, porque la conexion sigue abierta.
    - La carpeta de trabajo es por equipo y la trae run_finished.
    - El guion es de sh o de PowerShell segun el sistema del equipo (set_targets);
      en Windows no se pide contrasena de sudo.
    """

    def __init__(self) -> None:
        self.state = ConsoleState.NO_TARGET
        super().__init__()
        self.command = ""
        self.outcome: Outcome | None = None
        self.history = CommandHistory()
        self._places: dict[str, Place] = {}
        self._systems: dict[str, str] = {}  # sistema de cada equipo, de su anuncio
        self._system = OS_LINUX  # el del equipo al que va el comando en curso
        self._started_at = 0.0

    @property
    def is_running(self) -> bool:
        return self.state == ConsoleState.RUNNING

    @property
    def is_asking(self) -> bool:
        return self.state == ConsoleState.ASKING

    @property
    def busy(self) -> bool:
        return self.is_running or self.is_asking

    @property
    def prompt(self) -> str:
        """Carpeta del equipo elegido como la escribe un shell (~ al empezar)."""
        place = self._places.get(self.target)
        return short_path(place.cwd, place.home) if place else "~"

    # -- Transiciones ------------------------------------------

    def set_targets(
        self, targets: list[tuple[str, str]], systems: dict[str, str] | None = None
    ) -> None:
        """Equipos alcanzables (nombre, IP) y, si se sabe, el sistema de cada uno."""
        self._systems = dict(systems or {})
        super().set_targets(targets)

    def start_run(self, command: str, now: float) -> dict:
        command = command.strip()
        if self.busy:
            return {"ok": False, "message": "Ya corre un comando."}
        system = self._systems.get(self.target, OS_LINUX)
        if is_clear(command, system):
            self.history.add(command)
            self.outcome = None
            return {"ok": True, "clear": True, "asking": False, "command": command}
        if not self.target:
            return {"ok": False, "message": NO_TARGET.text}
        if not command:
            return {"ok": False, "message": "Escribe un comando."}
        self.history.add(command)
        self.command = command
        self.outcome = None
        self._system = system
        if needs_password(command, system):
            self.state = ConsoleState.ASKING
            return {"ok": True, "asking": True, "command": command}
        return self._begin(now, stdin=b"")

    def give_password(self, password: str, now: float) -> dict:
        """La contrasena de sudo pasa a stdin del comando; no queda en la logica."""
        if not self.is_asking:
            return {"ok": False, "message": "No hay un comando esperando contraseña."}
        return self._begin(now, stdin=(password + "\n").encode(ENCODING))

    def run_finished(
        self,
        ok: bool,
        status: int | None,
        now: float,
        message: str = "",
        hint: str = "",
        place: Place | None = None,
    ) -> None:
        if not self.is_running:
            return  # ya se cancelo: lo que llegue despues no cambia nada
        if place is not None:
            self._places[self.target] = place
        took = seconds_text(now - self._started_at)
        if not ok:
            self.outcome = Outcome(message, Tone.ERROR, hint)
        elif status is None:
            self.outcome = Outcome(f"Terminó sin código de salida en {took}.", Tone.WARNING)
        else:
            tone = Tone.OK if status == 0 else Tone.WARNING
            self.outcome = Outcome(f"Terminó con código {status} en {took}.", tone)
        self._settle()

    def cancel(self, now: float) -> bool:
        if self.is_asking:
            self.outcome = Outcome("No se corrió: faltó la contraseña de sudo.", Tone.NEUTRAL)
            self._settle()
            return True
        if not self.is_running:
            return False
        self.outcome = Outcome(
            f"Cancelado a los {seconds_text(now - self._started_at)}.", Tone.WARNING
        )
        self._settle()
        return True

    # -- Vista -------------------------------------------------

    def view(self) -> dict:
        address = self.address
        return {
            "state": self.state.value,
            "targets": list(self.targets),
            "target": self.target,
            "address": address,
            "running": self.is_running,
            "asking": self.is_asking,
            "prompt": self.prompt,
            "status": NO_TARGET if self.state == ConsoleState.NO_TARGET else None,
            "outcome": self.outcome,
        }

    # -- Helpers -----------------------------------------------

    def _begin(self, now: float, stdin: bytes) -> dict:
        place = self._places.get(self.target)
        cwd = place.cwd if place else ""
        script = wrap_command(self.command, cwd, bool(stdin), self._system)
        self.state = ConsoleState.RUNNING
        self._started_at = now
        return {
            "ok": True,
            "asking": False,
            "target": self.target,
            "command": self.command,
            "script": script,
            "stdin": stdin,
        }

    def _settle(self) -> None:
        super()._settle()
        self.state = ConsoleState.READY if self.target else ConsoleState.NO_TARGET


class OutputDecoder:
    """Bytes de cada flujo a texto, sin romper una letra partida entre dos trozos."""

    def __init__(self) -> None:
        self._decoders: dict[str, codecs.IncrementalDecoder] = {}

    def feed(self, stream: str, data: bytes) -> str:
        decoder = self._decoders.get(stream)
        if decoder is None:
            decoder = codecs.getincrementaldecoder(ENCODING)(errors="replace")
            self._decoders[stream] = decoder
        return decoder.decode(data).replace("\r\n", "\n")

    def flush(self) -> str:
        """Lo que quedo a medias al terminar; deja el decodificador listo para otro comando."""
        rest = "".join(decoder.decode(b"", final=True) for decoder in self._decoders.values())
        self._decoders.clear()
        return rest
