"""Coordinador del Chat: dos instancias locales con el bucle de red real.

Se emparejan con sus coordinadores de emparejar (como en la app), cada una ve
a la otra con una busqueda falsa y se escriben y pasan archivos en los dos
sentidos a carpetas de llegada en tmp_path. Los archivos se comparan por sha256.
"""

from __future__ import annotations

import hashlib
import os
import socket

import pytest

from core.async_loop import AsyncLoop
from modules.mod_02_pair._02_coordinator import PairCoordinator
from modules.mod_05_chat._05_coordinator import ChatCoordinator
from services.service_discovery import Peer
from services.service_identity import load_or_create_identity, save_device_name
from services.service_link import LinkSession, LinkSettings
from tests.test_02_coordinator_pair import LOCALHOST, LOOPBACK_NET, _free_port, _wait_until

MB = 1024 * 1024


def _random_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    return path


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Node:
    def __init__(self, loop, tmp_path, name, pair_port):
        save_device_name(tmp_path / name, name)
        identity = load_or_create_identity(tmp_path / name)
        self.inbox = tmp_path / f"llegada-{name}"
        settings = LinkSettings(
            LOCALHOST, 0, pair_port, LOOPBACK_NET, announce=False, inbox=self.inbox
        )
        self.seen: list[Peer] = []

        async def browse(host, own_name, seconds, subnet):
            return list(self.seen), 0.0

        self.link = LinkSession(identity, settings, browse)
        self.pair = PairCoordinator(loop, self.link, lambda: LOCALHOST, browse_every_ms=100)
        self.chat = ChatCoordinator(loop, self.link, refresh_every_ms=100)
        self.pair_views: list[dict] = []
        self.views: list[dict] = []
        self.badges: list[dict] = []
        self.pair.view_changed.connect(self.pair_views.append)
        self.chat.view_changed.connect(self.views.append)
        self.chat.badge_changed.connect(self.badges.append)

    @property
    def view(self) -> dict:
        return self.views[-1] if self.views else {"state": "", "entries": []}

    def entries(self) -> list:
        return self.view["entries"]


@pytest.fixture
def loop():
    loop = AsyncLoop()
    yield loop
    loop.stop()


def _paired(app, loop, tmp_path):
    pair_port = _free_port()
    a = _Node(loop, tmp_path, "equipo-a", pair_port)
    b = _Node(loop, tmp_path, "equipo-b", pair_port)
    for node in (a, b):
        node.pair.start()
        node.chat.start()
    _wait_until(app, lambda: a.pair_views and a.pair_views[-1]["state"] == "ONLINE")
    _wait_until(app, lambda: b.pair_views and b.pair_views[-1]["state"] == "ONLINE")
    b.seen.append(Peer("equipo-a", LOCALHOST, a.link.ssh_port))
    a.seen.append(Peer("equipo-b", LOCALHOST, b.link.ssh_port))
    a.pair.open_window()
    _wait_until(app, lambda: a.pair_views[-1]["window_open"])
    _wait_until(app, lambda: [r.address for r in b.pair_views[-1]["rows"]] == [LOCALHOST])
    b.pair.join("equipo-a", a.pair_views[-1]["code"])
    _wait_until(app, lambda: b.view["state"] == "READY" and a.view["state"] == "READY")
    return a, b, pair_port


def test_messages_and_files_both_ways(qt_application, loop, tmp_path):
    a, b, pair_port = _paired(qt_application, loop, tmp_path)
    assert (a.view["target"], b.view["target"]) == ("equipo-b", "equipo-a")

    assert not b.chat.write("   ")
    assert b.chat.write("hola desde b")
    _wait_until(qt_application, lambda: [e.state for e in b.entries()] == ["DELIVERED"])
    _wait_until(qt_application, lambda: a.entries())
    got = a.entries()[0]
    assert (got.text, got.peer, got.outgoing, got.state) == (
        "hola desde b",
        "equipo-b",
        False,
        "RECEIVED",
    )
    assert a.badges[-1]["unread"] == 1
    a.chat.set_visible(True)
    assert a.badges[-1]["unread"] == 0
    a.chat.write("respuesta de a")
    _wait_until(qt_application, lambda: len(b.entries()) == 2)
    assert b.entries()[1].text == "respuesta de a" and b.badges[-1]["unread"] == 1

    one = _random_file(tmp_path / "salida" / "uno.bin", 2 * MB)
    b.chat.send([one, tmp_path / "salida"])  # la carpeta se omite
    assert "carpetas" in b.view["outcome"].text
    _wait_until(qt_application, lambda: b.entries()[-1].state == "DELIVERED")
    _wait_until(qt_application, lambda: a.entries()[-1].state == "RECEIVED")
    assert (a.entries()[-1].text, a.entries()[-1].done) == ("uno.bin", 2 * MB)
    assert any(badge["busy"] for badge in a.badges)
    assert _sha256(a.inbox / "uno.bin") == _sha256(one)

    two = _random_file(tmp_path / "salida-a" / "dos.bin", MB)
    a.chat.send([two])
    _wait_until(qt_application, lambda: b.entries()[-1].state == "RECEIVED")
    assert _sha256(b.inbox / "dos.bin") == _sha256(two)

    big = _random_file(tmp_path / "salida" / "grande.bin", 64 * MB)
    b.chat.send([big])
    _wait_until(qt_application, lambda: b.entries()[-1].done > 0)
    b.chat.cancel(b.entries()[-1].entry_id)
    assert b.entries()[-1].state == "CANCELLED"
    _wait_until(qt_application, lambda: a.entries()[-1].state == "CUT")
    _wait_until(qt_application, lambda: not (a.inbox / "grande.bin.part").exists())

    for node in (b, a):
        node.chat.close()
        assert node.link.on_message is None and node.link.on_incoming is None
    b.pair.close()
    a.pair.close()
    with socket.socket() as sock:
        assert sock.connect_ex((LOCALHOST, pair_port)) != 0


def test_open_inbox_creates_the_arrival_folder(qt_application, loop, tmp_path):
    node = _Node(loop, tmp_path, "equipo-a", _free_port())
    assert not node.inbox.exists()
    assert node.chat.open_inbox() == str(node.inbox) and node.inbox.is_dir()
    node.chat.close()
