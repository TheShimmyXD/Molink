"""Maquina de estados del Chat: conversaciones, mensajes y archivos en los dos sentidos."""

from __future__ import annotations

from pathlib import Path

from modules.mod_05_chat.logic._05_logic_chat import MAX_ENTRIES, ChatLogic, ChatState, EntryState

DESK = ("sobremesa", "10.0.0.2")
SHOP = ("taller", "10.0.0.3")


def _ready(*targets):
    logic = ChatLogic()
    logic.set_targets(list(targets) or [DESK])
    return logic


def _states(logic, peer="sobremesa"):
    return [e.state for e in logic.conversations[peer]]


def test_no_target_until_a_peer_is_reachable():
    logic = ChatLogic()
    assert logic.state == ChatState.NO_TARGET
    assert logic.write("hola", 1.0) == {"ok": False, "message": logic.view()["status"].text}
    logic.set_targets([DESK])
    assert (logic.state, logic.target, logic.address) == (ChatState.READY, "sobremesa", "10.0.0.2")


def test_message_goes_out_and_is_delivered_or_failed():
    logic = _ready()
    assert not logic.write("   ", 1.0)["ok"]
    first = logic.write(" hola ", 1.0)
    second = logic.write("otra", 2.0)
    assert first["text"] == "hola" and first["target"] == "sobremesa"
    logic.text_finished(first["entry_id"], True)
    logic.text_finished(
        second["entry_id"], False, "sobremesa no confirmó el mensaje.", "Revisa la red."
    )
    logic.text_finished(second["entry_id"], True)  # llega tarde: no cambia nada
    entries = logic.view()["entries"]
    assert [e.state for e in entries] == [EntryState.DELIVERED, EntryState.FAILED]
    assert entries[1].note == "sobremesa no confirmó el mensaje."


def test_received_counts_unread_and_drops_repeats():
    logic = _ready(DESK, SHOP)
    assert logic.received("taller", "id-1", "hola", 1.0)
    assert not logic.received("taller", "id-1", "hola", 1.5)
    assert logic.received("sobremesa", "id-2", "aqui", 2.0)
    assert logic.badge()["unread"] == 2  # la pantalla no se ve
    logic.set_visible(True)
    assert logic.unread == {"taller": 1}
    assert logic.choose("taller") and logic.unread == {}
    logic.received("taller", "id-3", "otra", 3.0)
    assert logic.unread == {}  # se esta mirando
    peers = {p["name"]: p["unread"] for p in logic.view()["peers"]}
    assert peers == {"sobremesa": 0, "taller": 0}


def test_first_message_opens_its_conversation():
    logic = ChatLogic()
    logic.received("sobremesa", "id-1", "hola", 1.0)
    assert logic.target == "sobremesa" and logic.state == ChatState.OFFLINE
    logic.set_targets([DESK])
    assert logic.state == ChatState.READY


def test_conversation_stays_readable_when_the_peer_leaves():
    logic = _ready(DESK, SHOP)
    logic.write("hola", 1.0)
    logic.set_targets([SHOP])
    view = logic.view()
    assert (view["state"], view["target"]) == ("OFFLINE", "sobremesa")
    assert "salió de la red" in view["status"].text
    assert not logic.write("sigo", 2.0)["ok"]
    assert [p["online"] for p in view["peers"]] == [True, False]  # taller, sobremesa
    assert logic.choose("taller") and logic.state == ChatState.READY
    assert not logic.choose("nadie")


def test_files_go_one_by_one_and_failure_stops_the_rest_to_that_peer():
    logic = _ready()
    logic.add_files([(Path("/a/uno.bin"), 100), (Path("/a/dos.bin"), 50)], 0, 1.0)
    assert _states(logic) == [EntryState.QUEUED, EntryState.QUEUED]
    first = logic.start_next_file()
    assert first["path"] == Path("/a/uno.bin") and first["target"] == "sobremesa"
    assert not logic.start_next_file()["ok"]  # uno a la vez
    logic.file_progress(first["entry_id"], 40)
    assert logic.conversations["sobremesa"][0].percent == 40
    assert "Enviando uno.bin: 40 %" in logic.badge()["tooltip"]
    assert logic.file_finished(first["entry_id"], True, "uno (1).bin")
    done = logic.conversations["sobremesa"][0]
    assert (done.state, done.note, done.done) == (EntryState.DELIVERED, "uno (1).bin", 100)
    second = logic.start_next_file()
    logic.add_files([(Path("/a/tres.bin"), 10)], 0, 2.0)
    assert not logic.file_finished(
        second["entry_id"], False, "", "Se perdió la conexión.", "Revisa."
    )
    assert _states(logic)[1:] == [EntryState.FAILED, EntryState.FAILED]
    assert logic.conversations["sobremesa"][2].note == "No se envió."


def test_cancel_current_or_queued_file():
    logic = _ready()
    logic.add_files([(Path("/a/uno.bin"), 100), (Path("/a/dos.bin"), 50)], 0, 1.0)
    first = logic.start_next_file()
    queued = logic.conversations["sobremesa"][1].entry_id
    assert logic.cancel_file(queued) == "queued"
    assert logic.cancel_file(first["entry_id"]) == "current"
    assert logic.cancel_file(first["entry_id"]) == ""
    assert not logic.file_finished(first["entry_id"], False, "", "tarde")  # ya cancelado
    assert _states(logic) == [EntryState.CANCELLED, EntryState.CANCELLED]
    assert logic.sending_file is None and not logic.start_next_file()["ok"]


def test_folders_are_skipped_and_offline_does_not_queue():
    logic = _ready()
    logic.add_files([], 2, 1.0)
    assert "Se omitieron 2" in logic.outcome.text
    logic.write("hola", 1.0)
    logic.set_targets([])
    logic.add_files([(Path("/a/uno.bin"), 1)], 0, 2.0)
    assert len(logic.conversations["sobremesa"]) == 1 and "salió" in logic.outcome.text


def test_incoming_file_shows_progress_and_ends_once():
    logic = _ready()
    logic.incoming("sobremesa", 7, "START", "foto.jpg", 0, 200, 1.0)
    logic.incoming("sobremesa", 7, "PROGRESS", "foto.jpg", 50, 200, 1.1)
    assert logic.badge() == {
        "unread": 1,
        "busy": True,
        "tooltip": "Recibiendo foto.jpg: 25 % (50 B de 200 B)",
    }
    logic.incoming("sobremesa", 7, "DONE", "foto (1).jpg", 200, 200, 1.2)
    logic.incoming("sobremesa", 7, "PROGRESS", "foto.jpg", 10, 200, 1.3)  # tarde: se ignora
    entry = logic.conversations["sobremesa"][0]
    assert (entry.state, entry.note, entry.done) == (EntryState.RECEIVED, "foto (1).jpg", 200)
    logic.incoming("sobremesa", 8, "START", "otro.bin", 0, 10, 2.0)
    logic.incoming("sobremesa", 8, "CUT", "otro.bin", 4, 10, 2.1)
    assert _states(logic)[1] == EntryState.CUT and not logic.badge()["busy"]


def test_old_finished_entries_are_trimmed():
    logic = _ready()
    for i in range(MAX_ENTRIES + 5):
        logic.received("sobremesa", f"id-{i}", "x", float(i))
    entries = logic.conversations["sobremesa"]
    assert len(entries) == MAX_ENTRIES and entries[0].key == "id-5"
