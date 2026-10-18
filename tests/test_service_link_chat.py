"""Chat por la sesion: dos instancias en 127.0.0.1 emparejadas por la ventana.

Cada mensaje llega con el nombre del que escribe, el canal se reutiliza y se
reabre si el otro reinicio la app. Ningun texto de mensaje llega a los logs.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from services import service_chat
from services.service_discovery import Peer
from services.service_link import LinkError, LinkSession, LinkSettings
from tests.test_service_link import LOCALHOST, LOOPBACK_NET, _identity


def _settings():
    return LinkSettings(LOCALHOST, 0, 0, LOOPBACK_NET, announce=False)


async def _chatting_pair(a, b, inbox_a, inbox_b):
    """a y b emparejados, cada uno ve al otro y escucha el chat."""
    seen: dict[str, list[Peer]] = {"a": [], "b": []}

    async def browse_a(*_):
        return list(seen["a"]), 0.0

    async def browse_b(*_):
        return list(seen["b"]), 0.0

    first = LinkSession(a, _settings(), browse_a, on_message=inbox_a.append)
    second = LinkSession(b, _settings(), browse_b, on_message=inbox_b.append)
    await first.start()
    await second.start()
    window = await first.open_window()
    waiting = asyncio.create_task(first.wait_window())
    await second.join(window.code, LOCALHOST, window.port)
    await waiting
    seen["a"].append(Peer("equipo-b", LOCALHOST, second.ssh_port))
    seen["b"].append(Peer("equipo-a", LOCALHOST, first.ssh_port))
    await first.browse()
    await second.browse()
    return first, second, seen


def test_messages_go_both_ways_with_the_sender_name(tmp_path, caplog):
    a, b = _identity(tmp_path, "equipo-a"), _identity(tmp_path, "equipo-b")
    got_a, got_b = [], []

    async def scenario():
        first, second, _ = await _chatting_pair(a, b, got_a, got_b)
        try:
            one = await second.say("equipo-a", "hola secreto")
            channel = second._chats["equipo-a"][1]
            two = await second.say("equipo-a", "otra vez")
            assert second._chats["equipo-a"][1] is channel
            back = await first.say("equipo-b", "respuesta")
            return one, two, back
        finally:
            await first.close()
            await second.close()

    with caplog.at_level(logging.DEBUG):
        one, two, back = asyncio.run(scenario())
    assert [(m.message_id, m.text, m.peer) for m in got_a] == [
        (one, "hola secreto", "equipo-b"),
        (two, "otra vez", "equipo-b"),
    ]
    assert [(m.message_id, m.text, m.peer) for m in got_b] == [(back, "respuesta", "equipo-a")]
    ours = [r.getMessage() for r in caplog.records if not r.name.startswith("asyncssh")]
    assert ours
    assert not [m for m in ours if "secreto" in m or "respuesta" in m]


def test_channel_reopens_after_the_other_restarts(tmp_path):
    a, b = _identity(tmp_path, "equipo-a"), _identity(tmp_path, "equipo-b")
    got_a, got_b = [], []

    async def scenario():
        first, second, seen = await _chatting_pair(a, b, got_a, got_b)
        try:
            await second.say("equipo-a", "antes")
            await first.close()
            await first.start()
            seen["b"][:] = [Peer("equipo-a", LOCALHOST, first.ssh_port)]
            await second.browse()
            await second.say("equipo-a", "despues")
        finally:
            await first.close()
            await second.close()
        assert second._chats == {}

    asyncio.run(scenario())
    assert [m.text for m in got_a] == ["antes", "despues"]


def test_unheard_long_and_unseen_messages_explain_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(service_chat, "ACK_TIMEOUT_S", 0.5)
    a, b = _identity(tmp_path, "equipo-a"), _identity(tmp_path, "equipo-b")
    got_a, got_b = [], []

    async def scenario():
        first, second, seen = await _chatting_pair(a, b, got_a, got_b)
        try:
            with pytest.raises(LinkError, match="pasa de 64 KiB"):
                await second.say("equipo-a", "x" * service_chat.MAX_LINE)
            first.on_message = None
            with pytest.raises(LinkError, match="no confirmó"):
                await second.say("equipo-a", "nadie escucha")
            seen["b"].clear()
            second._seen.clear()
            with pytest.raises(LinkError, match="no está en la red"):
                await second.say("equipo-a", "sin red")
        finally:
            await first.close()
            await second.close()

    asyncio.run(scenario())
    assert got_a == []
