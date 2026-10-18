"""Estados del Chat: una conversacion por equipo con mensajes y archivos en los dos sentidos.

Logica pura: la hora llega como argumento y la red la maneja el coordinador.
El texto de los mensajes vive solo en memoria mientras la app esta abierta;
nunca va a un log ni a disco.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from logic._00_logic_targets import NO_TARGET, Outcome, TargetChoice, Tone, human_size

MAX_ENTRIES = 500  # por conversacion; se borran los mas viejos ya terminados


class ChatState(StrEnum):
    NO_TARGET = "NO_TARGET"  # ningun equipo emparejado en la red ni conversacion abierta
    READY = "READY"  # el equipo elegido esta en la red: se puede escribir
    OFFLINE = "OFFLINE"  # se ve la conversacion, pero el equipo salio de la red


class EntryKind(StrEnum):
    TEXT = "text"
    FILE = "file"


class EntryState(StrEnum):
    QUEUED = "QUEUED"  # archivo saliente esperando su turno
    SENDING = "SENDING"  # saliendo (texto sin acuse o archivo en camino)
    DELIVERED = "DELIVERED"  # el otro lo acuso o el archivo quedo alla
    RECEIVING = "RECEIVING"  # archivo entrante en camino
    RECEIVED = "RECEIVED"  # mensaje o archivo que llego completo
    FAILED = "FAILED"  # saliente que no llego
    CANCELLED = "CANCELLED"  # archivo saliente cancelado aqui
    CUT = "CUT"  # archivo entrante que no termino


ACTIVE = (EntryState.QUEUED, EntryState.SENDING, EntryState.RECEIVING)


@dataclass(frozen=True, slots=True)
class Entry:
    """Una burbuja de la conversacion."""

    entry_id: int
    peer: str
    kind: EntryKind
    outgoing: bool
    state: EntryState
    at: float  # hora de pared, para mostrar
    text: str = ""  # el mensaje, o el nombre del archivo
    size: int = 0
    done: int = 0  # bytes enviados o recibidos
    note: str = ""  # nombre con que quedo alla, o que paso si fallo
    hint: str = ""
    path: Path | None = None  # archivo saliente
    key: str = ""  # id del mensaje, o de la transferencia entrante

    @property
    def percent(self) -> int:
        return 100 if self.size == 0 else min(100, self.done * 100 // self.size)


class ChatLogic(TargetChoice):
    """
    MAQUINA DE ESTADOS - MODULO CHAT

    NO_TARGET
        -> set_targets([...])            -> READY

    READY
        -> write(text)                   -> burbuja SENDING (sigue READY)
        -> add_files([...])              -> burbujas QUEUED; start_next_file las envia
        -> set_targets sin el elegido    -> OFFLINE si hay conversacion,
                                            si no READY con otro o NO_TARGET

    OFFLINE
        -> set_targets con el elegido    -> READY
        -> choose(otro)                  -> READY

    Cada burbuja tiene su propio estado (EntryState). Los mensajes salen en
    paralelo; los archivos, de uno en uno en el orden en que se soltaron.

    REGLAS
    - Sin PySide6 ni I/O; la hora llega como argumento y los tamanos los mide
      el coordinador.
    - Se puede cambiar de conversacion en cualquier momento (busy es False):
      lo que va en camino sigue y se ve en la conversacion de su equipo.
    - Un mensaje con un id ya visto en esa conversacion se descarta (reintento
      del otro lado por otro canal).
    - Lo que llega a una conversacion que no se esta mirando cuenta como no leido.
    """

    def __init__(self) -> None:
        super().__init__()
        self.state = ChatState.NO_TARGET
        self.conversations: dict[str, list[Entry]] = {}
        self.unread: dict[str, int] = {}
        self.visible = False
        self.outcome: Outcome | None = None
        self._next_id = 0
        self._queue: list[int] = []  # archivos salientes por enviar
        self._sending_file: int | None = None
        self._incoming: dict[tuple[str, int], int] = {}  # (equipo, transfer_id) -> entry_id

    # -- Conversacion ------------------------------------------

    def choose(self, name: str) -> bool:
        if name not in self._names() and name not in self.conversations:
            return False
        self.target = name
        self._settle()
        self._mark_read()
        return True

    def set_visible(self, visible: bool) -> None:
        self.visible = visible
        self._mark_read()

    # -- Mensajes ----------------------------------------------

    def write(self, text: str, now: float) -> dict:
        text = text.strip()
        if self.state != ChatState.READY:
            return {"ok": False, "message": self._why_not()}
        if not text:
            return {"ok": False, "message": "Escribe un mensaje."}
        entry = self._add(self.target, EntryKind.TEXT, True, EntryState.SENDING, now, text=text)
        return {"ok": True, "entry_id": entry.entry_id, "target": self.target, "text": text}

    def text_finished(self, entry_id: int, ok: bool, message: str = "", hint: str = "") -> None:
        entry = self._find(entry_id)
        if entry is None or entry.state != EntryState.SENDING:
            return
        if ok:
            self._put(replace(entry, state=EntryState.DELIVERED))
        else:
            self._put(replace(entry, state=EntryState.FAILED, note=message, hint=hint))

    def received(self, peer: str, message_id: str, text: str, now: float) -> bool:
        """Mensaje que llego de peer; False si era un repetido."""
        if any(e.key == message_id for e in self.conversations.get(peer, [])):
            return False
        self._add(peer, EntryKind.TEXT, False, EntryState.RECEIVED, now, text=text, key=message_id)
        self._count_unread(peer)
        return True

    # -- Archivos que salen ------------------------------------

    def add_files(self, files: list[tuple[Path, int]], skipped: int, now: float) -> None:
        """Pone en cola, en la conversacion elegida, los archivos soltados o elegidos."""
        if skipped:
            self.outcome = Outcome(
                f"Se omitieron {skipped}: solo se envían archivos, no carpetas.",
                Tone.WARNING,
                "Comprime la carpeta y envía el archivo.",
            )
        elif files:
            self.outcome = None
        if not files:
            return
        if self.state != ChatState.READY:
            self.outcome = Outcome(self._why_not(), Tone.WARNING)
            return
        for path, size in files:
            entry = self._add(
                self.target,
                EntryKind.FILE,
                True,
                EntryState.QUEUED,
                now,
                path.name,
                size,
                path=path,
            )
            self._queue.append(entry.entry_id)

    def start_next_file(self) -> dict:
        """El siguiente archivo de la cola, si no hay otro en camino."""
        if self._sending_file is not None or not self._queue:
            return {"ok": False}
        entry = self._find(self._queue.pop(0))
        if entry is None:
            return self.start_next_file()
        self._sending_file = entry.entry_id
        self._put(replace(entry, state=EntryState.SENDING))
        return {"ok": True, "entry_id": entry.entry_id, "target": entry.peer, "path": entry.path}

    def file_progress(self, entry_id: int, sent: int) -> None:
        entry = self._find(entry_id)
        if entry is not None and entry.state == EntryState.SENDING:
            self._put(replace(entry, done=sent))

    def file_finished(
        self, entry_id: int, ok: bool, arrived_as: str = "", message: str = "", hint: str = ""
    ) -> bool:
        """Cierra el archivo en curso; True si queda otro en la cola.

        Si falla, los que esperaban al mismo equipo tampoco se envian: lo mas
        probable es que la red se haya caido.
        """
        if entry_id != self._sending_file:
            return False  # ya se cancelo
        self._sending_file = None
        entry = self._find(entry_id)
        if entry is not None:
            if ok:
                note = arrived_as if arrived_as != entry.text else ""
                self._put(replace(entry, state=EntryState.DELIVERED, done=entry.size, note=note))
            else:
                self._put(replace(entry, state=EntryState.FAILED, note=message, hint=hint))
                for queued in list(self._queue):
                    other = self._find(queued)
                    if other is not None and other.peer == entry.peer:
                        self._queue.remove(queued)
                        self._put(
                            replace(other, state=EntryState.FAILED, note="No se envió.", hint=hint)
                        )
        return bool(self._queue)

    def cancel_file(self, entry_id: int) -> str:
        """Cancela un archivo saliente: 'current' si iba en camino, 'queued' si esperaba, '' si no."""
        entry = self._find(entry_id)
        if entry is None or not entry.outgoing:
            return ""
        if entry_id == self._sending_file:
            self._sending_file = None
            self._put(replace(entry, state=EntryState.CANCELLED))
            return "current"
        if entry_id in self._queue:
            self._queue.remove(entry_id)
            self._put(replace(entry, state=EntryState.CANCELLED))
            return "queued"
        return ""

    @property
    def sending_file(self) -> int | None:
        return self._sending_file

    # -- Archivos que llegan -----------------------------------

    def incoming(
        self,
        peer: str,
        transfer_id: int,
        kind: str,
        name: str,
        received: int,
        total: int,
        now: float,
    ) -> None:
        """Aviso del servidor (START, PROGRESS, DONE, CUT) de un archivo que llega de peer."""
        key = (peer, transfer_id)
        if kind == "START":
            entry = self._add(
                peer, EntryKind.FILE, False, EntryState.RECEIVING, now, name, total, received
            )
            self._incoming[key] = entry.entry_id
            self._count_unread(peer)
            return
        entry = self._find(self._incoming.get(key, -1))
        if entry is None:
            return
        if kind == "PROGRESS":
            self._put(replace(entry, done=received))
        elif kind == "DONE":
            del self._incoming[key]
            note = name if name != entry.text else ""
            self._put(replace(entry, state=EntryState.RECEIVED, done=received, note=note))
        elif kind == "CUT":
            del self._incoming[key]
            self._put(replace(entry, state=EntryState.CUT, done=received))

    # -- Vista -------------------------------------------------

    def view(self) -> dict:
        reachable = self._names()
        names = reachable + [n for n in self.conversations if n not in reachable]
        return {
            "state": self.state.value,
            "target": self.target,
            "address": self.address,
            "peers": [
                {"name": n, "online": n in reachable, "unread": self.unread.get(n, 0)}
                for n in names
            ],
            "entries": list(self.conversations.get(self.target, [])),
            "status": self._status(),
            "outcome": self.outcome,
            "badge": self.badge(),
        }

    def badge(self) -> dict:
        """Lo que muestra el boton Chat desde otra pantalla: no leidos y avance."""
        active = [
            e
            for entries in self.conversations.values()
            for e in entries
            if e.kind == EntryKind.FILE and e.state in (EntryState.SENDING, EntryState.RECEIVING)
        ]
        lines = []
        for e in active:
            verb = "Enviando" if e.outgoing else "Recibiendo"
            lines.append(
                f"{verb} {e.text}: {e.percent} % ({human_size(e.done)} de {human_size(e.size)})"
            )
        return {
            "unread": sum(self.unread.values()),
            "busy": bool(active),
            "tooltip": "\n".join(lines),
        }

    # -- Helpers -----------------------------------------------

    def _settle(self) -> None:
        reachable = self._names()
        if self.target in reachable:
            self.state = ChatState.READY
        elif self.target and self.target in self.conversations:
            self.state = ChatState.OFFLINE
        else:
            super()._settle()
            self.state = ChatState.READY if self.target else ChatState.NO_TARGET

    def _status(self) -> Outcome | None:
        if self.state == ChatState.NO_TARGET:
            return NO_TARGET
        if self.state == ChatState.OFFLINE:
            return Outcome(
                f"{self.target} salió de la red.",
                Tone.NEUTRAL,
                "Puedes leer la conversación; para escribir, abre Molink allá.",
            )
        return None

    def _why_not(self) -> str:
        status = self._status()
        return status.text if status is not None else ""

    def _add(
        self,
        peer: str,
        kind: EntryKind,
        outgoing: bool,
        state: EntryState,
        now: float,
        text: str = "",
        size: int = 0,
        done: int = 0,
        path: Path | None = None,
        key: str = "",
    ) -> Entry:
        self._next_id += 1
        entry = Entry(
            self._next_id, peer, kind, outgoing, state, now, text, size, done, path=path, key=key
        )
        entries = self.conversations.setdefault(peer, [])
        entries.append(entry)
        while len(entries) > MAX_ENTRIES:
            old = next((e for e in entries if e.state not in ACTIVE), None)
            if old is None:
                break
            entries.remove(old)
        if not self.target:
            self.target = peer
        if peer == self.target:
            self._settle()
        return entry

    def _find(self, entry_id: int) -> Entry | None:
        for entries in self.conversations.values():
            for entry in entries:
                if entry.entry_id == entry_id:
                    return entry
        return None

    def _put(self, entry: Entry) -> None:
        entries = self.conversations[entry.peer]
        for i, old in enumerate(entries):
            if old.entry_id == entry.entry_id:
                entries[i] = entry
                return

    def _count_unread(self, peer: str) -> None:
        if not (self.visible and peer == self.target):
            self.unread[peer] = self.unread.get(peer, 0) + 1

    def _mark_read(self) -> None:
        if self.visible and self.target:
            self.unread.pop(self.target, None)
