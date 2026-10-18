"""El que recibe ve el avance: dos instancias en 127.0.0.1 con llaves en tmp_path.

El servidor avisa START con el total, PROGRESS con bytes que solo crecen y un
unico final: DONE con el nombre con que quedo, o CUT si el envio se cancela o
la conexion se cae. Ningun nombre de archivo llega a los logs.
"""

from __future__ import annotations

import asyncio
import logging

import asyncssh
import pytest

from services import service_transfer
from services.service_discovery import Peer
from services.service_link import LinkSession, LinkSettings
from services.service_transfer import IncomingKind, send_file
from tests.test_service_transfer import (
    LOCALHOST,
    LOOPBACK_NET,
    MB,
    _connected,
    _identity,
    _random_file,
    _sha256,
    keys,  # noqa: F401 (fixture)
)

FINAL = (IncomingKind.DONE, IncomingKind.CUT)


@pytest.fixture(autouse=True)
def _every_write(monkeypatch):
    # Sin espera entre avisos: la prueba ve cada bloque.
    monkeypatch.setattr(service_transfer, "PROGRESS_EVERY_S", 0.0)


def _check_sequence(events, size):
    assert events[0].kind is IncomingKind.START
    assert (events[0].received, events[0].total) == (0, size)
    received = [e.received for e in events]
    assert received == sorted(received)
    assert [e.kind for e in events].count(IncomingKind.START) == 1
    assert sum(e.kind in FINAL for e in events) == 1
    assert events[-1].kind in FINAL
    assert len({e.transfer_id for e in events}) == 1


def test_receiver_sees_total_progress_and_done(tmp_path, keys):  # noqa: F811
    size = 2 * MB + 5
    source = _random_file(tmp_path / "avance.bin", size)
    inbox = tmp_path / "llegada"
    events = []

    async def scenario():
        async with _connected(keys, inbox, events.append) as conn:
            return await send_file(conn, source)

    name = asyncio.run(scenario())
    _check_sequence(events, size)
    progress = [e for e in events if e.kind is IncomingKind.PROGRESS]
    assert len(progress) >= 2 * MB // service_transfer.BLOCK_SIZE
    done = events[-1]
    assert done.kind is IncomingKind.DONE
    assert (done.name, done.received) == (name, size)
    assert done.peer_key == keys["paired"].public_data
    assert _sha256(inbox / name) == _sha256(source)


def test_taken_name_is_reported_with_the_final_name(tmp_path, keys):  # noqa: F811
    inbox = tmp_path / "llegada"
    inbox.mkdir()
    (inbox / "dato.bin").write_bytes(b"ya estaba")
    source = _random_file(tmp_path / "dato.bin", MB)
    events = []

    async def scenario():
        async with _connected(keys, inbox, events.append) as conn:
            await send_file(conn, source)

    asyncio.run(scenario())
    assert events[0].name == "dato (1).bin"
    assert events[-1].name == "dato (1).bin"


def test_cancel_is_seen_as_cut(tmp_path, keys):  # noqa: F811
    size = 32 * MB
    source = _random_file(tmp_path / "grande.bin", size)
    inbox = tmp_path / "llegada"
    events = []

    async def scenario():
        async with _connected(keys, inbox, events.append) as conn:
            moving = asyncio.Event()
            task = asyncio.create_task(
                send_file(conn, source, lambda sent, _t: sent > 0 and moving.set())
            )
            await asyncio.wait_for(moving.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    _check_sequence(events, size)
    assert events[-1].kind is IncomingKind.CUT
    assert events[-1].received < size
    assert list(inbox.iterdir()) == []


def test_dropped_connection_is_seen_as_cut(tmp_path, keys):  # noqa: F811
    size = 32 * MB
    source = _random_file(tmp_path / "grande.bin", size)
    events = []

    async def scenario():
        async with _connected(keys, tmp_path / "llegada", events.append) as conn:
            moving = asyncio.Event()
            task = asyncio.create_task(
                send_file(conn, source, lambda sent, _t: sent > 0 and moving.set())
            )
            await asyncio.wait_for(moving.wait(), 5)
            conn.abort()
            with pytest.raises((asyncssh.Error, OSError)):
                await task
            # El servidor se entera del corte en su propio turno del bucle.
            for _ in range(50):
                if events and events[-1].kind in FINAL:
                    break
                await asyncio.sleep(0.05)

    asyncio.run(scenario())
    _check_sequence(events, size)
    assert events[-1].kind is IncomingKind.CUT


def test_listener_failure_does_not_break_the_send(tmp_path, keys):  # noqa: F811
    source = _random_file(tmp_path / "terco.bin", MB)
    inbox = tmp_path / "llegada"

    def broken(_event):
        raise RuntimeError("falla de quien escucha")

    async def scenario():
        async with _connected(keys, inbox, broken) as conn:
            return await send_file(conn, source)

    name = asyncio.run(scenario())
    assert _sha256(inbox / name) == _sha256(source)


def test_link_reports_who_sends_and_logs_no_names(tmp_path, caplog):
    a, b = _identity(tmp_path, "equipo-a"), _identity(tmp_path, "equipo-b")
    source = _random_file(tmp_path / "nombre-secreto.bin", MB)
    events = []
    seen: list[Peer] = []

    async def browse(host, own_name, seconds, subnet):
        return list(seen), 0.0

    async def scenario():
        receiver = LinkSession(
            a,
            LinkSettings(LOCALHOST, 0, 0, LOOPBACK_NET, announce=False, inbox=tmp_path / "in"),
            browse,
            on_incoming=events.append,
        )
        sender = LinkSession(b, LinkSettings(LOCALHOST, 0, 0, LOOPBACK_NET, announce=False), browse)
        await receiver.start()
        await sender.start()
        try:
            window = await receiver.open_window()
            waiting = asyncio.create_task(receiver.wait_window())
            await sender.join(window.code, LOCALHOST, window.port)
            await waiting
            seen.append(Peer("equipo-a", LOCALHOST, receiver.ssh_port))
            await sender.browse()
            await sender.send("equipo-a", source, lambda *_: None)
        finally:
            await receiver.close()
            await sender.close()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(scenario())
    _check_sequence(events, MB)
    assert {e.peer for e in events} == {"equipo-b"}
    assert events[-1].kind is IncomingKind.DONE
    # asyncssh nombra los archivos en DEBUG; la app deja su logger en WARNING.
    ours = [r.getMessage() for r in caplog.records if not r.name.startswith("asyncssh")]
    assert ours
    assert not [m for m in ours if "nombre-secreto" in m]
