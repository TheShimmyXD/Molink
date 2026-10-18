"""Estados de la pantalla de emparejar, sin Qt ni red."""

from __future__ import annotations

from modules.mod_02_pair.logic._02_logic_pair import LinkState, PairLogic, PeerRow, Tone


def _online(paired=()) -> PairLogic:
    logic = PairLogic()
    logic.link_starting("192.0.2.10")
    logic.set_paired(list(paired))
    assert logic.link_started()["ok"]
    return logic


def test_starting_then_searching_then_peers():
    logic = PairLogic()
    logic.link_starting("192.0.2.10")
    assert logic.status().text == "Abriendo Molink en 192.0.2.10..."
    logic.link_started()
    assert logic.status().text == "Buscando equipos en la red..." and logic.status().busy
    logic.peers_found([])
    assert "Nadie más" in logic.status().text and logic.status().hint
    logic.peers_found([("sobremesa", "192.0.2.20")])
    assert logic.status().text == "1 equipo en la red."
    assert logic.rows() == [PeerRow("sobremesa", "192.0.2.20", paired=False)]


def test_link_error_says_what_to_do_and_retry_starts_again():
    logic = PairLogic()
    logic.link_starting("192.0.2.10")
    payload = logic.link_failed("El puerto 47820 ya está ocupado.", "Cierra el otro Molink.")
    assert payload["ok"] is False and logic.state is LinkState.ERROR
    assert logic.status().tone is Tone.ERROR and logic.status().hint
    assert not logic.peers_found([("sobremesa", "192.0.2.20")])["ok"]
    logic.link_starting("192.0.2.10")
    assert logic.link_started()["ok"] and logic.is_online


def test_lost_network_counts_down_and_the_line_follows():
    logic = _online(paired=["sobremesa"])
    assert logic.link_started(47820)["ok"] is False  # ya estaba en la red
    logic = PairLogic()
    logic.link_starting("192.0.2.10")
    logic.set_paired(["sobremesa"])
    logic.link_started(47820)
    assert logic.connection(0.0).text == "Buscando a sobremesa..."
    logic.peers_found([("sobremesa", "192.0.2.20")])
    line = logic.connection(0.0)
    assert line.text == "Conectado a sobremesa" and line.address == "192.0.2.10:47820"

    assert logic.retry_in(0.0) == 0 and not logic.schedule_retry(0.0, 5.0)["ok"]
    assert logic.link_lost()["ok"] is False and logic.state is LinkState.ERROR
    assert logic.rows() == [PeerRow("sobremesa", "", paired=True)]
    assert logic.retry_in(0.0) == 0
    assert logic.schedule_retry(100.0, 5.0)["ok"]
    assert logic.retry_in(100.0) == 5 and logic.retry_in(101.2) == 4 and logic.retry_in(106.0) == 0
    line = logic.connection(101.2)
    assert line.text == "Se cortó la red, reintentando en 4 s" and line.can_retry
    assert not logic.link_lost()["ok"]  # no se pierde dos veces

    logic.link_starting("192.0.2.11")
    assert logic.retry_in(101.2) == 0
    assert logic.connection(101.2).text == "Abriendo Molink en 192.0.2.11..."


def test_join_validates_code_and_runs_one_at_a_time():
    logic = _online()
    logic.peers_found([("sobremesa", "192.0.2.20"), ("taller", "192.0.2.30")])
    bad = logic.start_join("sobremesa", "12345")
    assert not bad["ok"] and logic.rows()[0].error == "El código tiene 6 dígitos."
    good = logic.start_join("sobremesa", "000 000")
    assert good["ok"] and good["address"] == "192.0.2.20" and "000" not in good["status"]
    assert logic.rows()[0].joining and logic.rows()[0].error == ""
    assert logic.status().text == "Emparejando con sobremesa..."
    assert not logic.start_join("taller", "000000")["ok"]
    assert not logic.start_join("nadie", "000000")["ok"]


def test_join_result_marks_paired_or_keeps_the_error_on_the_row():
    logic = _online()
    logic.peers_found([("sobremesa", "192.0.2.20")])
    logic.start_join("sobremesa", "000000")
    logic.join_finished("sobremesa", False, "El código no coincide.", "Revisa el código.")
    assert logic.rows()[0].error == "El código no coincide. Revisa el código."
    logic.start_join("sobremesa", "000000")
    assert logic.join_finished("sobremesa", True)["ok"]
    assert logic.rows() == [PeerRow("sobremesa", "192.0.2.20", paired=True)]
    assert logic.status().text == "Emparejado con sobremesa." and logic.status().tone is Tone.OK
    assert not logic.start_join("sobremesa", "000000")["ok"]


def test_paired_peers_show_even_when_not_in_the_network_and_can_be_forgotten():
    logic = _online(paired=["viejo", "sobremesa"])
    logic.peers_found([("sobremesa", "192.0.2.20"), ("nuevo", "192.0.2.40")])
    assert [(r.name, r.address, r.paired) for r in logic.rows()] == [
        ("nuevo", "192.0.2.40", False),
        ("sobremesa", "192.0.2.20", True),
        ("viejo", "", True),
    ]
    logic.forgotten("viejo")
    assert [r.name for r in logic.rows()] == ["nuevo", "sobremesa"]


def test_window_countdown_and_how_it_ends():
    logic = _online()
    logic.window_opened("000000", 47821, 120.0, now=1000.0)
    view = logic.view(now=1000.5)
    assert view["window_open"] and view["code"] == "000000" and view["remaining"] == 120
    assert logic.remaining(1119.2) == 1 and logic.remaining(1121.0) == 0
    assert "000000" not in logic.status().text
    logic.window_finished("EXPIRED")
    assert not logic.window_open and logic.view(1121.0)["code"] == ""
    assert "Se acabó el tiempo" in logic.status().text and logic.status().tone is Tone.ERROR
    logic.window_opened("000000", 47821, 120.0, now=2000.0)
    logic.window_finished("PAIRED", "sobremesa")
    assert logic.rows() == [PeerRow("sobremesa", "", paired=True)]
    assert logic.status().text == "Emparejado con sobremesa."


def test_window_closed_by_user_leaves_no_notice_and_failure_explains():
    logic = _online()
    logic.peers_found([])
    logic.window_opened("000000", 47821, 120.0, now=0.0)
    logic.window_finished("CLOSED")
    assert "Nadie más" in logic.status().text
    logic.window_failed("El puerto 47821 ya está ocupado.", "Cierra el otro Molink.")
    assert logic.status().tone is Tone.ERROR and not logic.window_open
