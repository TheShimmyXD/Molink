"""Orden de consola: el primer contacto entre dos instancias locales.

Cada instancia tiene su carpeta en tmp_path, su nombre y sus puertos (0, uno
libre) en 127.0.0.1, sin anuncio. El codigo sale de las lineas que serve le
muestra al usuario y pasa al otro lado dentro del proceso; nunca se imprime.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import socket

import pytest

from services.service_console import (
    EXIT_USAGE,
    ConsoleError,
    format_code,
    main,
    pair,
    parse_target,
    run_remote,
    serve,
)
from services.service_identity import load_or_create_identity, save_device_name
from services.service_paired import add_paired, load_paired
from services.service_pairing_listener import own_record

LOCALHOST = "127.0.0.1"
LOOPBACK_NET = "127.0.0.0/8"
READY_TIMEOUT_S = 5


def _identity(tmp_path, name):
    save_device_name(tmp_path / name, name)
    return load_or_create_identity(tmp_path / name)


@pytest.fixture
def a(tmp_path):
    return _identity(tmp_path, "equipo-a")


@pytest.fixture
def b(tmp_path):
    return _identity(tmp_path, "equipo-b")


class _Node:
    """Una instancia con serve corriendo en segundo plano y sus lineas."""

    def __init__(self, identity, pairing: bool):
        self.identity = identity
        self.lines: list[str] = []
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(
            serve(
                identity,
                LOCALHOST,
                0,
                self._stop,
                self.lines.append,
                pair_port=0 if pairing else None,
                network=LOOPBACK_NET,
                announce=False,
            )
        )

    async def line(self, pattern: str) -> re.Match:
        async def find():
            while True:
                for text in self.lines:
                    if match := re.search(pattern, text):
                        return match
                if self._task.done():
                    self._task.result()
                await asyncio.sleep(0.01)

        return await asyncio.wait_for(find(), READY_TIMEOUT_S)

    async def ssh_port(self) -> int:
        return int((await self.line(r"escuchando en [\d.]+:(\d+)"))[1])

    async def close(self) -> None:
        self._stop.set()
        await asyncio.wait_for(self._task, READY_TIMEOUT_S)


async def _run(source, name, command, port):
    out, err = io.BytesIO(), io.BytesIO()
    status = await run_remote(source, name, command, (LOCALHOST, port), None, out, err)
    return status, out.getvalue(), err.getvalue()


def test_first_contact_pairs_and_runs_hostname_both_ways(a, b):
    async def scenario():
        node_a = _Node(a, pairing=True)
        node_b = _Node(b, pairing=False)
        try:
            found = await node_a.line(r"Codigo de emparejamiento: (\d{3}) (\d{3}) \(puerto (\d+)")
            joined = await pair(b, found[1] + found[2], LOCALHOST, int(found[3]))
            await node_a.line(r"Emparejado con equipo-b")
            to_a = await _run(b, "equipo-a", "hostname", await node_a.ssh_port())
            to_b = await _run(a, "equipo-b", "hostname; exit 3", await node_b.ssh_port())
        finally:
            await node_a.close()
            await node_b.close()
        return joined, to_a, to_b

    joined, to_a, to_b = asyncio.run(scenario())
    expected = (socket.gethostname() + os.linesep).encode()
    assert joined.name == "equipo-a"
    assert to_a == (0, expected, b"")
    assert to_b == (3, expected, b"")
    assert [p.name for p in load_paired(a.data_dir)] == ["equipo-b"]
    assert [p.name for p in load_paired(b.data_dir)] == ["equipo-a"]


def test_window_report_when_closed_without_pairing(a):
    async def scenario():
        node = _Node(a, pairing=True)
        await node.line(r"Codigo de emparejamiento")
        await node.close()
        return node.lines

    lines = asyncio.run(scenario())
    assert not any("Emparejado" in text for text in lines)


def test_run_against_peer_that_did_not_pair_back_is_denied(a, b):
    add_paired(b.data_dir, own_record(a))

    async def scenario():
        node = _Node(a, pairing=False)
        try:
            with pytest.raises(ConsoleError, match="no tiene emparejado"):
                await _run(b, "equipo-a", "hostname", await node.ssh_port())
        finally:
            await node.close()

    asyncio.run(scenario())


def test_run_against_server_with_other_host_key_is_refused(a, b, tmp_path):
    add_paired(b.data_dir, own_record(a))
    impostor = _identity(tmp_path, "impostor")
    add_paired(impostor.data_dir, own_record(b))

    async def scenario():
        node = _Node(impostor, pairing=False)
        try:
            with pytest.raises(ConsoleError, match="no es el equipo-a"):
                await _run(b, "equipo-a", "hostname", await node.ssh_port())
        finally:
            await node.close()

    asyncio.run(scenario())


def test_run_unknown_peer_and_closed_port(a, b):
    with pytest.raises(ConsoleError, match="ningun equipo"):
        asyncio.run(_run(b, "equipo-a", "hostname", 9))
    add_paired(b.data_dir, own_record(a))
    with socket.socket() as sock:
        sock.bind((LOCALHOST, 0))
        free = sock.getsockname()[1]
    with pytest.raises(ConsoleError, match="No se pudo conectar"):
        asyncio.run(_run(b, "equipo-a", "hostname", free))


def test_pair_with_bad_code_or_no_window(b):
    with pytest.raises(ConsoleError):
        asyncio.run(pair(b, "12a456", LOCALHOST, 9))
    with socket.socket() as sock:
        sock.bind((LOCALHOST, 0))
        free = sock.getsockname()[1]
    with pytest.raises(ConsoleError, match="No se pudo conectar"):
        asyncio.run(pair(b, "123456", LOCALHOST, free))


def test_serve_on_busy_port_explains_it(a):
    async def scenario():
        with socket.socket() as sock:
            sock.bind((LOCALHOST, 0))
            sock.listen()
            with pytest.raises(ConsoleError, match="ocupado"):
                await serve(
                    a,
                    LOCALHOST,
                    sock.getsockname()[1],
                    asyncio.Event(),
                    print,
                    None,
                    LOOPBACK_NET,
                    False,
                )

    asyncio.run(scenario())


def test_parse_target_and_format_code():
    assert parse_target("192.0.2.7", 47820) == ("192.0.2.7", 47820)
    assert parse_target("192.0.2.7:5000", 47820) == ("192.0.2.7", 5000)
    with pytest.raises(ConsoleError):
        parse_target("equipo-a", 47820)
    assert format_code("012345") == "012 345"


def test_main_peers_and_run_without_command(a, b, capsys):
    add_paired(a.data_dir, own_record(b))
    assert main(["--data", str(a.data_dir), "peers"]) == 0
    out = capsys.readouterr().out
    assert "Este equipo: equipo-a" in out and "equipo-b  equipo SHA256:" in out
    assert main(["--data", str(a.data_dir), "run", "equipo-b", "--to", LOCALHOST]) == EXIT_USAGE
    assert "Falta el comando" in capsys.readouterr().err
    assert main(["--data", str(a.data_dir), "run", "equipo-x", "--to", LOCALHOST, "--", "ls"]) == 2
    assert "llamado equipo-x" in capsys.readouterr().err
