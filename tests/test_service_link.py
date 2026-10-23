"""Enlace de la app: dos instancias locales que se emparejan por la ventana.

Cada una con su carpeta en tmp_path y puertos libres (0) en 127.0.0.1, sin
anuncio (mDNS no va por loopback); la busqueda se reemplaza por una falsa.
El codigo pasa de un lado al otro dentro del proceso y nunca se imprime.
"""

from __future__ import annotations

import asyncio
import socket
import time

import pytest

from core.async_loop import AsyncLoop
from services.service_discovery import Peer
from services.service_identity import load_or_create_identity, save_device_name
from services.service_link import LinkError, LinkSession, LinkSettings
from services.service_paired import load_paired

LOCALHOST = "127.0.0.1"
LOOPBACK_NET = "127.0.0.0/8"


def _identity(tmp_path, name):
    save_device_name(tmp_path / name, name)
    return load_or_create_identity(tmp_path / name)


def _session(identity, browse_fn=None, ssh_port=0):
    settings = LinkSettings(LOCALHOST, ssh_port, 0, LOOPBACK_NET, announce=False)
    return LinkSession(identity, settings, browse_fn)


def _port_is_free(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex((LOCALHOST, port)) != 0


def test_pair_through_the_window_and_forget(tmp_path):
    a = _identity(tmp_path, "equipo-a")
    b = _identity(tmp_path, "equipo-b")

    async def scenario():
        shower, joiner = _session(a), _session(b)
        await shower.start()
        await joiner.start()
        window = await shower.open_window()
        assert len(window.code) == 6 and 0 < window.seconds <= 120
        waiting = asyncio.create_task(shower.wait_window())
        peer = await joiner.join(window.code, LOCALHOST, window.port)
        assert peer.name == "equipo-a"
        peer_b, why = await waiting
        assert peer_b.name == "equipo-b" and why == "PAIRED"
        assert shower.paired_names() == ["equipo-b"] and joiner.paired_names() == ["equipo-a"]
        assert await joiner.forget("equipo-a") and joiner.paired_names() == []
        ports = (shower.ssh_port, window.port, joiner.ssh_port)
        await shower.close()
        await joiner.close()
        return ports

    ports = asyncio.run(scenario())
    assert all(_port_is_free(port) for port in ports)
    assert load_paired(b.data_dir) == []


def test_bad_code_and_closed_window_explain_what_to_do(tmp_path):
    a = _identity(tmp_path, "equipo-a")
    b = _identity(tmp_path, "equipo-b")

    async def scenario():
        shower, joiner = _session(a), _session(b)
        await shower.start()
        window = await shower.open_window()
        wrong = f"{(int(window.code) + 1) % 10**6:06d}"
        with pytest.raises(LinkError, match="no coincide") as bad:
            await joiner.join(wrong, LOCALHOST, window.port)
        assert bad.value.hint
        with pytest.raises(LinkError, match="6 dígitos"):
            await joiner.join("12345", LOCALHOST, window.port)
        waiting = asyncio.create_task(shower.wait_window())
        await asyncio.sleep(0)
        await shower.close_window()
        assert await waiting == (None, "CLOSED")
        with pytest.raises(LinkError, match="No se pudo llegar"):
            await joiner.join(window.code, LOCALHOST, window.port)
        await shower.close()

    asyncio.run(scenario())
    assert load_paired(b.data_dir) == []


def test_busy_port_and_no_network_are_link_errors(tmp_path):
    a = _identity(tmp_path, "equipo-a")

    async def scenario():
        with socket.socket() as sock:
            sock.bind((LOCALHOST, 0))
            sock.listen()
            with pytest.raises(LinkError, match="ocupado") as busy:
                await _session(a, ssh_port=sock.getsockname()[1]).start()
            assert "otro Molink" in busy.value.hint
        with pytest.raises(LinkError, match="ninguna red"):
            await LinkSession(a, LinkSettings("")).start()

    asyncio.run(scenario())


def test_browse_uses_the_subnet_and_own_name(tmp_path):
    a = _identity(tmp_path, "equipo-a")
    calls = []

    async def fake_browse(host, own_name, seconds, subnet):
        calls.append((host, own_name, seconds, str(subnet)))
        return [Peer("equipo-b", "127.0.0.2", 47820)], 0.1

    async def scenario():
        link = _session(a, fake_browse)
        await link.start()
        try:
            return await link.browse(0.5)
        finally:
            await link.close()

    assert asyncio.run(scenario()) == [Peer("equipo-b", "127.0.0.2", 47820)]
    assert calls == [(LOCALHOST, "equipo-a", 0.5, LOOPBACK_NET)]


def test_async_loop_runs_in_its_thread_and_stops_cleanly(tmp_path):
    a = _identity(tmp_path, "equipo-a")
    loop = AsyncLoop()
    link = _session(a)
    loop.submit(link.start()).result(5)
    port = link.ssh_port
    assert not _port_is_free(port)
    forever = loop.submit(asyncio.sleep(3600))
    assert loop.stop(link.close())
    assert forever.cancelled() and _port_is_free(port) and not loop.running
    with pytest.raises(RuntimeError):
        loop.submit(asyncio.sleep(0))


async def _paired_pair(a, b, seen: list[Peer]):
    """a muestra su codigo y b lo escribe; b ve a a con la busqueda falsa."""

    async def browse(host, own_name, seconds, subnet):
        return list(seen), 0.0

    shower, joiner = _session(a), _session(b, browse)
    await shower.start()
    await joiner.start()
    window = await shower.open_window()
    waiting = asyncio.create_task(shower.wait_window())
    await joiner.join(window.code, LOCALHOST, window.port)
    await waiting
    return shower, joiner


@pytest.mark.linux_only
def test_run_streams_both_outputs_and_cancel_ends_it(tmp_path):
    a = _identity(tmp_path, "equipo-a")
    b = _identity(tmp_path, "equipo-b")
    seen: list[Peer] = []

    async def scenario():
        shower, joiner = await _paired_pair(a, b, seen)
        with pytest.raises(LinkError, match="no está en la red"):
            await joiner.run("equipo-a", "hostname", lambda *_: None)
        seen.append(Peer("equipo-a", LOCALHOST, shower.ssh_port))
        await joiner.browse()
        assert await joiner.reachable() == seen
        with pytest.raises(LinkError, match="ya no está emparejado"):
            await joiner.run("taller", "hostname", lambda *_: None)

        chunks: list[tuple[str, bytes]] = []
        status = await joiner.run(
            "equipo-a", "printf uno; printf dos >&2; exit 3", lambda *c: chunks.append(c)
        )
        assert status == 3
        assert sorted(chunks) == [("stderr", b"dos"), ("stdout", b"uno")]

        first = asyncio.Event()
        task = asyncio.create_task(
            joiner.run("equipo-a", "echo listo; sleep 30", lambda *_: first.set())
        )
        await asyncio.wait_for(first.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        await shower.close()
        await joiner.close()
        assert await joiner.reachable() == []

    asyncio.run(scenario())


def test_closed_link_restarts_in_another_host(tmp_path):
    a = _identity(tmp_path, "equipo-a")

    async def scenario():
        link = LinkSession(a, LinkSettings("", 0, 0, LOOPBACK_NET, announce=False))
        with pytest.raises(LinkError, match="ninguna red"):
            await link.start()
        await link.start(LOCALHOST)
        port = link.ssh_port
        assert link.host == LOCALHOST and port > 0
        await link.close()
        await link.start(LOCALHOST)
        assert link.ssh_port > 0
        await link.close()
        return port

    assert _port_is_free(asyncio.run(scenario()))


def test_a_peer_stays_seen_through_short_mdns_gaps(tmp_path):
    a = _identity(tmp_path, "equipo-a")
    rounds = [[Peer("equipo-b", "127.0.0.2", 47820)], [], [], []]
    now = [0.0]

    async def browse(host, own_name, seconds, subnet):
        return rounds.pop(0), 0.0

    async def scenario():
        link = _session(a, browse)
        link.clock = lambda: now[0]
        await link.start()
        try:
            seen = [await link.browse()]
            for at in (5.0, 15.0, 15.1):
                now[0] = at
                seen.append(await link.browse())
            return [[peer.name for peer in peers] for peers in seen]
        finally:
            await link.close()

    assert asyncio.run(scenario()) == [["equipo-b"], ["equipo-b"], ["equipo-b"], []]


def test_stop_also_cancels_tasks_born_while_cancelling():
    loop = AsyncLoop()
    born: list[asyncio.Task] = []

    async def spawns_on_cancel():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            born.append(asyncio.ensure_future(asyncio.sleep(3600)))
            raise

    loop.submit(spawns_on_cancel())
    time.sleep(0.05)
    assert loop.stop()
    assert len(born) == 1 and born[0].cancelled()
