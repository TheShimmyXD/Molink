"""Linea de estado de la conexion: cada estado del enlace da su texto y su tono."""

from __future__ import annotations

from logic._00_logic_connection import ERROR, ONLINE, STARTING, connection_line
from logic._00_logic_targets import Tone

HOST = "192.0.2.10"


def test_starting_says_where():
    line = connection_line(STARTING, HOST, 0, [], [])
    assert line.text == "Abriendo Molink en 192.0.2.10..."
    assert line.tone is Tone.WARNING and not line.can_retry


def test_error_counts_down_and_can_retry():
    error = ("Se cortó la red.", "Vuelve solo cuando haya red.")
    line = connection_line(ERROR, HOST, 0, ["sobremesa"], [], error, retry_in=4)
    assert line.text == "Se cortó la red, reintentando en 4 s"
    assert line.tone is Tone.ERROR and line.can_retry
    assert line.hint == "Vuelve solo cuando haya red." and line.address == ""
    assert connection_line(ERROR, HOST, 0, [], [], error).text == "Se cortó la red, reintentando..."


def test_online_without_paired():
    line = connection_line(ONLINE, HOST, 47820, [], ["sobremesa"])
    assert line.text == "Sin equipo emparejado"
    assert line.tone is Tone.NEUTRAL and line.address == "192.0.2.10:47820"


def test_paired_but_not_seen_is_searching():
    line = connection_line(ONLINE, HOST, 47820, ["sobremesa"], ["otro"])
    assert line.text == "Buscando a sobremesa..."
    assert line.tone is Tone.WARNING


def test_connected_lists_only_reachable_paired():
    line = connection_line(
        ONLINE, HOST, 47820, ["sobremesa", "taller", "laptop"], ["taller", "sobremesa"]
    )
    assert line.text == "Conectado a sobremesa y taller"
    assert line.tone is Tone.OK and not line.can_retry
    three = connection_line(ONLINE, HOST, 0, ["a", "b", "c"], ["a", "b", "c"])
    assert three.text == "Conectado a a, b y c" and three.address == HOST
