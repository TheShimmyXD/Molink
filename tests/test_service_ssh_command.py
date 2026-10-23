"""Comando remoto entre dos instancias locales emparejadas entre si.

Cada instancia tiene su carpeta de datos en tmp_path, su identidad y su
servidor en 127.0.0.1; cada una conoce a la otra por paired.json. Se prueba
la salida en vivo, el codigo de salida y la cancelacion sin huerfanos.
"""

from __future__ import annotations

import asyncio
import socket
import time
from contextlib import AsyncExitStack
from pathlib import Path

import pytest

from services.service_identity import load_or_create_identity
from services.service_paired import PeerRecord, add_paired
from services.service_ssh_client import STDERR, STDOUT, connect_peer, stream_command
from services.service_ssh_server import exit_code, start_molink_server

LOCALHOST = "127.0.0.1"
LOOPBACK_NET = "127.0.0.0/8"
GONE_TIMEOUT_S = 5


def _record(identity, name):
    return PeerRecord.build(
        name,
        identity.user_key.export_public_key().decode("ascii"),
        identity.host_key.export_public_key().decode("ascii"),
    )


@pytest.fixture
def instances(tmp_path):
    """Dos instancias, a y b, emparejadas en los dos sentidos."""
    a = load_or_create_identity(tmp_path / "a")
    b = load_or_create_identity(tmp_path / "b")
    add_paired(a.data_dir, _record(b, "equipo-b"))
    add_paired(b.data_dir, _record(a, "equipo-a"))
    return a, b


class _Running:
    """Las dos instancias con su servidor abierto; se cierran al salir."""

    def __init__(self, instances):
        self.a, self.b = instances
        self.ports: dict[str, int] = {}
        self._stack = AsyncExitStack()

    async def __aenter__(self):
        for name, identity in (("a", self.a), ("b", self.b)):
            handle = await start_molink_server(identity, LOCALHOST, 0, LOOPBACK_NET)
            self._stack.push_async_callback(handle.close)
            self.ports[name] = handle.port
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    def connect(self, source, target):
        """Conexion de la instancia source al servidor de target."""
        src, dst = getattr(self, source), getattr(self, target)
        return connect_peer(
            LOCALHOST, self.ports[target], src.user_key, dst.host_key.convert_to_public()
        )


def _collector():
    chunks = []

    def on_output(name, data):
        chunks.append((time.monotonic(), name, data))

    return chunks, on_output


def _joined(chunks, name):
    return b"".join(data for _, stream, data in chunks if stream == name)


def _alive(pid):
    """True si el proceso existe y no es un zombi."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"


def _port_is_free(port):
    with socket.socket() as sock:
        return sock.connect_ex((LOCALHOST, port)) != 0


def test_exit_code_like_a_shell():
    assert exit_code(0) == 0
    assert exit_code(3) == 3
    assert exit_code(-15) == 143


def test_hostname_both_ways(instances):
    async def scenario():
        results = {}
        async with _Running(instances) as running:
            for source, target in (("a", "b"), ("b", "a")):
                chunks, on_output = _collector()
                async with running.connect(source, target) as conn:
                    status = await stream_command(conn, "hostname", on_output)
                results[source + target] = (status, _joined(chunks, STDOUT))
        return results, running.ports

    results, ports = asyncio.run(scenario())
    for status, stdout in results.values():
        assert status == 0
        assert stdout.decode().strip() == socket.gethostname()
    assert all(_port_is_free(port) for port in ports.values())


def test_failing_command_returns_status_and_stderr(instances):
    async def scenario():
        chunks, on_output = _collector()
        async with _Running(instances) as running, running.connect("a", "b") as conn:
            status = await stream_command(conn, "echo malo >&2; exit 3", on_output)
        return status, chunks

    status, chunks = asyncio.run(scenario())
    assert status == 3
    assert _joined(chunks, STDERR) == b"malo\n"
    assert _joined(chunks, STDOUT) == b""


def test_command_not_found_is_127(instances):
    async def scenario():
        async with _Running(instances) as running, running.connect("a", "b") as conn:
            return await stream_command(conn, "orden-que-no-existe-xyz", lambda *_: None)

    assert asyncio.run(scenario()) == 127


def test_stdin_reaches_the_command_and_then_ends(instances):
    """Lo que se manda por stdin llega al comando (sudo -S); sin nada, fin de entrada."""

    async def scenario():
        results = []
        async with _Running(instances) as running, running.connect("a", "b") as conn:
            for data in (b"linea uno\nlinea dos\n", b""):
                chunks, on_output = _collector()
                status = await stream_command(conn, "cat; echo fin", on_output, stdin=data)
                results.append((status, _joined(chunks, STDOUT)))
        return results

    sent, empty = asyncio.run(scenario())
    assert sent == (0, b"linea uno\nlinea dos\nfin\n")
    assert empty == (0, b"fin\n")


def test_output_arrives_live(instances):
    """La primera linea llega antes de que el comando termine."""

    async def scenario():
        chunks, on_output = _collector()
        async with _Running(instances) as running, running.connect("a", "b") as conn:
            status = await stream_command(conn, "echo uno; sleep 0.5; echo dos", on_output)
            finished_at = time.monotonic()
        return status, chunks, finished_at

    status, chunks, finished_at = asyncio.run(scenario())
    assert status == 0
    assert _joined(chunks, STDOUT) == b"uno\ndos\n"
    first_at = chunks[0][0]
    assert finished_at - first_at >= 0.4


def test_long_command_is_cancelled_without_orphans(instances):
    """Se cancela un comando que dejo un proceso de fondo: mueren los dos."""

    async def scenario():
        pids = asyncio.get_running_loop().create_future()

        def on_output(name, data):
            if name == STDOUT and not pids.done():
                pids.set_result([int(pid) for pid in data.split()])

        async with _Running(instances) as running, running.connect("a", "b") as conn:
            task = asyncio.ensure_future(
                stream_command(conn, "sleep 60 & echo $$ $!; wait", on_output)
            )
            shell_pid, background_pid = await asyncio.wait_for(pids, GONE_TIMEOUT_S)
            assert _alive(shell_pid) and _alive(background_pid)
            started = time.monotonic()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            while (_alive(shell_pid) or _alive(background_pid)) and (
                time.monotonic() - started < GONE_TIMEOUT_S
            ):
                await asyncio.sleep(0.05)
            gone_after = time.monotonic() - started
            # La conexion sigue sirviendo despues de cancelar.
            status = await stream_command(conn, "true", lambda *_: None)
        return shell_pid, background_pid, gone_after, status

    shell_pid, background_pid, gone_after, status = asyncio.run(scenario())
    assert not _alive(shell_pid)
    assert not _alive(background_pid)
    assert gone_after < GONE_TIMEOUT_S
    assert status == 0


def test_windows_runs_powershell_and_kills_the_tree(monkeypatch, tmp_path):
    from services import service_process

    calls = []

    class FakeChild:
        pid = 4321

        async def wait(self):
            return 1

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeChild()

    real_write = service_process.write_script
    monkeypatch.setattr(service_process, "is_windows", lambda: True)
    monkeypatch.setattr(service_process.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(service_process, "write_script", lambda c: real_write(c, str(tmp_path)))

    async def scenario():
        child = await service_process.spawn("hostname")
        await service_process.terminate(child)
        return child

    child = asyncio.run(scenario())
    (spawn_args, spawn_kwargs), (kill_args, _) = calls
    assert spawn_args[0] == "powershell.exe" and spawn_args[-2] == "-File"
    script = Path(spawn_args[-1]).read_bytes()
    assert script.startswith(b"\xef\xbb\xbf") and b"\r\nhostname\r\n" in script
    assert spawn_kwargs["creationflags"] == service_process.WINDOWS_FLAGS
    assert "start_new_session" not in spawn_kwargs
    assert kill_args == ("taskkill.exe", "/T", "/F", "/PID", "4321")
    # El falso PowerShell no corre el autoborrado, como un .ps1 con error de sintaxis.
    service_process.release(child)
    assert not Path(spawn_args[-1]).exists()
    service_process.release(child)
