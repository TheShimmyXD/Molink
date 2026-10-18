"""Coordinador de emparejar: dos instancias locales con el bucle de red real.

Cada una con su carpeta en tmp_path, servidor en un puerto libre de
127.0.0.1 y sin anuncio; la busqueda es falsa. El codigo pasa de la vista de
una a la otra dentro del proceso, como lo copiaria el usuario.
"""

from __future__ import annotations

import socket
import time

import pytest

from core.async_loop import AsyncLoop
from modules.mod_02_pair._02_coordinator import PairCoordinator
from services.service_discovery import Peer
from services.service_identity import load_or_create_identity, save_device_name
from services.service_link import LinkSession, LinkSettings

LOCALHOST = "127.0.0.1"
LOOPBACK_NET = "127.0.0.0/8"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((LOCALHOST, 0))
        return sock.getsockname()[1]


def _wait_until(app, condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "no se llego al estado esperado"
        app.processEvents()
        time.sleep(0.01)


class _Node:
    def __init__(self, loop, tmp_path, name, pair_port, seen, ssh_port=0, host=None, **timing):
        save_device_name(tmp_path / name, name)
        identity = load_or_create_identity(tmp_path / name)
        settings = LinkSettings(LOCALHOST, ssh_port, pair_port, LOOPBACK_NET, announce=False)

        async def browse(host, own_name, seconds, subnet):
            return list(seen), 0.0

        self.link = LinkSession(identity, settings, browse)
        # host: lista de un elemento que la prueba cambia para simular un corte de red.
        host = host or [LOCALHOST]
        self.coordinator = PairCoordinator(loop, self.link, lambda: host[0], **timing)
        self.views: list[dict] = []
        self.lines: list = []
        self.coordinator.view_changed.connect(self.views.append)
        self.coordinator.connection_changed.connect(self.lines.append)

    @property
    def view(self) -> dict:
        return self.views[-1]


@pytest.fixture
def loop():
    loop = AsyncLoop()
    yield loop
    loop.stop()


def test_pair_from_the_screen_both_ways_and_forget(qt_application, loop, tmp_path):
    pair_port = _free_port()
    a = _Node(loop, tmp_path, "equipo-a", pair_port, [])
    b = _Node(loop, tmp_path, "equipo-b", pair_port, [Peer("equipo-a", LOCALHOST, 47820)])
    a.coordinator.start()
    b.coordinator.start()
    _wait_until(qt_application, lambda: [r.name for r in b.view["rows"]] == ["equipo-a"])
    assert "Nadie más" in a.view["status"].text

    a.coordinator.open_window()
    _wait_until(qt_application, lambda: a.view["window_open"])
    assert 0 < a.view["remaining"] <= 120 and a.view["window_port"] == pair_port
    b.coordinator.join("equipo-a", "12345")
    assert b.view["rows"][0].error == "El código tiene 6 dígitos."
    b.coordinator.join("equipo-a", a.view["code"])
    assert b.view["status"].text == "Emparejando con equipo-a..."
    _wait_until(qt_application, lambda: b.view["rows"][0].paired)
    _wait_until(qt_application, lambda: not a.view["window_open"])
    assert a.view["status"].text == "Emparejado con equipo-b."
    assert [(r.name, r.paired) for r in a.view["rows"]] == [("equipo-b", True)]

    b.coordinator.forget("equipo-a")
    _wait_until(qt_application, lambda: not b.view["rows"][0].paired)
    a.coordinator.close()
    b.coordinator.close()
    with socket.socket() as sock:
        assert sock.connect_ex((LOCALHOST, pair_port)) != 0


def test_busy_port_shows_error_and_retry_recovers(qt_application, loop, tmp_path):
    with socket.socket() as sock:
        sock.bind((LOCALHOST, 0))
        sock.listen()
        busy = sock.getsockname()[1]
        node = _Node(loop, tmp_path, "equipo-a", _free_port(), [], ssh_port=busy)
        node.coordinator.start()
        _wait_until(qt_application, lambda: node.view["state"] == "ERROR")
    assert "ocupado" in node.view["status"].text and node.view["status"].hint
    node.coordinator.start()
    _wait_until(qt_application, lambda: node.view["state"] == "ONLINE")
    node.coordinator.close()


def test_closing_the_window_by_hand_leaves_no_notice(qt_application, loop, tmp_path):
    node = _Node(loop, tmp_path, "equipo-a", _free_port(), [])
    node.coordinator.start()
    _wait_until(qt_application, lambda: "Nadie" in node.view["status"].text)
    node.coordinator.open_window()
    _wait_until(qt_application, lambda: node.view["window_open"])
    node.coordinator.close_window()
    _wait_until(qt_application, lambda: not node.view["window_open"])
    assert "Nadie más" in node.view["status"].text
    node.coordinator.close()


def test_lost_network_closes_the_port_and_comes_back_alone(qt_application, loop, tmp_path):
    host = [LOCALHOST]
    ssh_port = _free_port()
    node = _Node(
        loop, tmp_path, "equipo-a", _free_port(), [], ssh_port, host, watch_ms=50, retry_s=0.4
    )
    node.coordinator.start()
    _wait_until(
        qt_application, lambda: node.lines and node.lines[-1].text == "Sin equipo emparejado"
    )
    assert node.lines[-1].address == f"{LOCALHOST}:{ssh_port}"

    host[0] = ""  # se fue la wifi
    _wait_until(qt_application, lambda: node.view["state"] == "ERROR")
    assert node.lines[-1].text.startswith("Se cortó la red, reintentando")
    assert node.lines[-1].can_retry

    def port_closed() -> bool:
        with socket.socket() as sock:
            return sock.connect_ex((LOCALHOST, ssh_port)) != 0

    _wait_until(qt_application, port_closed)
    # Sin IP el reintento falla y vuelve a contar; con la IP de vuelta abre solo.
    _wait_until(qt_application, lambda: "ninguna red" in node.lines[-1].text, timeout=3.0)
    host[0] = LOCALHOST
    _wait_until(qt_application, lambda: node.view["state"] == "ONLINE", timeout=3.0)
    assert not port_closed()
    node.coordinator.close()
    assert port_closed()
