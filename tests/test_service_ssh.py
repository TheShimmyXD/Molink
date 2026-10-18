"""Ensayo local del canal: servidor en 127.0.0.1 con llaves generadas en tmp_path.

Cada prueba abre su servidor y lo cierra aunque falle; al final el puerto
queda libre. Las pruebas negativas (T14) cubren cada via de entrada rechazada:
llave no emparejada, contrasena, origen fuera de la red, reenvio de agente,
de X11 y de puertos, socket Unix y consola interactiva.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from contextlib import asynccontextmanager

import asyncssh
import pytest

from services import service_ssh_server
from services.service_identity import load_or_create_identity
from services.service_paired import PeerRecord, add_paired, remove_paired
from services.service_ssh_client import run_command
from services.service_ssh_server import is_allowed_origin, start_molink_server, start_server

LOCALHOST = "127.0.0.1"
LOOPBACK_NET = "127.0.0.0/8"
CLOSE_TIMEOUT_S = 5


def _make_key(tmp_path, name):
    path = tmp_path / name
    asyncssh.generate_private_key("ssh-ed25519").write_private_key(str(path))
    path.chmod(0o600)
    return asyncssh.read_private_key(str(path))


def _public_line(key):
    return key.export_public_key().decode("ascii").strip()


@pytest.fixture
def keys(tmp_path):
    keys = {name: _make_key(tmp_path, name) for name in ("host", "paired", "stranger", "peer_host")}
    # El otro equipo solo conoce la llave publica del servidor.
    keys["host_pub"] = keys["host"].convert_to_public()
    keys["stranger_pub"] = keys["stranger"].convert_to_public()
    return keys


@asynccontextmanager
async def _server(keys, network=LOOPBACK_NET):
    handle = await start_server(LOCALHOST, 0, keys["host"], lambda: [keys["paired"]], network)
    try:
        yield handle
    finally:
        await handle.close()


def _connect(keys, port, **options):
    return asyncssh.connect(
        LOCALHOST,
        port,
        username="molink",
        client_keys=[keys["paired"]],
        known_hosts=([keys["host_pub"]], [], []),
        config=None,
        **{"agent_path": None, **options},
    )


def _port_is_free(port):
    with socket.socket() as sock:
        return sock.connect_ex((LOCALHOST, port)) != 0


# -- Origen permitido (puro) ---------------------------------------------


def test_is_allowed_origin():
    assert is_allowed_origin("192.0.2.25", "192.0.2.0/24")
    assert not is_allowed_origin("198.51.100.7", "192.0.2.0/24")
    assert is_allowed_origin("::ffff:192.0.2.25", "192.0.2.0/24")
    assert not is_allowed_origin("::ffff:198.51.100.7", "192.0.2.0/24")
    assert not is_allowed_origin("no-es-ip", "192.0.2.0/24")


@pytest.mark.parametrize(
    ("host", "network"), [("0.0.0.0", "0.0.0.0/0"), ("::", "::/0"), (LOCALHOST, "192.0.2.0/24")]
)
def test_start_server_refuses_bad_listen_host(keys, host, network):
    with pytest.raises(ValueError):
        asyncio.run(start_server(host, 0, keys["host"], lambda: [], network))


# -- Lo que si debe funcionar --------------------------------------------


def test_paired_key_runs_hostname(keys):
    async def scenario():
        async with _server(keys) as handle:
            result = await run_command(
                LOCALHOST, handle.port, keys["paired"], keys["host_pub"], "hostname"
            )
            return handle.port, result

    port, result = asyncio.run(scenario())
    assert result.exit_status == 0
    assert result.stdout.decode().strip() == socket.gethostname()
    assert _port_is_free(port)


def test_exit_status_and_stderr_are_returned(keys):
    async def scenario():
        async with _server(keys) as handle:
            return await run_command(
                LOCALHOST, handle.port, keys["paired"], keys["host_pub"], "echo fallo >&2; exit 3"
            )

    result = asyncio.run(scenario())
    assert result.exit_status == 3
    assert result.stderr == b"fallo\n"


def test_molink_server_reads_paired_list_live(tmp_path, keys):
    """La llave de paired.json entra; al quitar el emparejamiento ya no."""
    identity = load_or_create_identity(tmp_path / "data")
    host_pub = identity.host_key.convert_to_public()
    peer = PeerRecord.build(
        "sobremesa", _public_line(keys["paired"]), _public_line(keys["peer_host"])
    )
    add_paired(identity.data_dir, peer)

    async def scenario():
        handle = await start_molink_server(identity, LOCALHOST, 0, LOOPBACK_NET)
        try:
            first = await run_command(LOCALHOST, handle.port, keys["paired"], host_pub, "true")
            remove_paired(identity.data_dir, "sobremesa")
            with pytest.raises(asyncssh.PermissionDenied):
                await run_command(LOCALHOST, handle.port, keys["paired"], host_pub, "true")
            return handle.port, first
        finally:
            await handle.close()

    port, first = asyncio.run(scenario())
    assert first.exit_status == 0
    assert _port_is_free(port)


def test_close_cuts_open_sessions_and_frees_port(keys):
    async def scenario():
        handle = await start_server(
            LOCALHOST, 0, keys["host"], lambda: [keys["paired"]], LOOPBACK_NET
        )
        conn = await _connect(keys, handle.port)
        try:
            await asyncio.wait_for(handle.close(), CLOSE_TIMEOUT_S)
            await asyncio.wait_for(conn.wait_closed(), CLOSE_TIMEOUT_S)
        finally:
            conn.close()
        return handle.port

    assert _port_is_free(asyncio.run(scenario()))


# -- Pruebas negativas (T14) ---------------------------------------------


def test_unpaired_key_is_rejected(keys):
    async def scenario():
        async with _server(keys) as handle:
            await run_command(
                LOCALHOST, handle.port, keys["stranger"], keys["host_pub"], "hostname"
            )

    with pytest.raises(asyncssh.PermissionDenied):
        asyncio.run(scenario())


def test_password_is_rejected(keys):
    async def scenario():
        async with _server(keys) as handle:
            await asyncssh.connect(
                LOCALHOST,
                handle.port,
                username="molink",
                password="cualquiera",
                client_keys=None,
                known_hosts=([keys["host_pub"]], [], []),
                agent_path=None,
                config=None,
                preferred_auth="password,keyboard-interactive",
            )

    with pytest.raises(asyncssh.PermissionDenied):
        asyncio.run(scenario())


def test_origin_outside_network_is_cut_before_auth(keys, caplog):
    """Desde 127.0.0.2 hacia un servidor que solo admite 127.0.0.1/32."""

    async def scenario():
        async with _server(keys, network="127.0.0.1/32") as handle:
            await _connect(keys, handle.port, local_addr=("127.0.0.2", 0))

    caplog.set_level(logging.INFO, logger=service_ssh_server.__name__)
    with pytest.raises((asyncssh.DisconnectError, ConnectionError)) as caught:
        asyncio.run(scenario())
    assert not isinstance(caught.value, asyncssh.PermissionDenied)
    messages = [record.getMessage() for record in caplog.records]
    assert any("fuera de 127.0.0.1/32" in m for m in messages)
    # Se corto antes de que la llave llegara a validarse.
    assert not any("Llave" in m for m in messages)


def test_unknown_server_key_is_rejected_by_client(keys):
    async def scenario():
        async with _server(keys) as handle:
            await run_command(
                LOCALHOST, handle.port, keys["paired"], keys["stranger_pub"], "hostname"
            )

    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        asyncio.run(scenario())


def test_port_forwarding_is_refused(keys):
    async def scenario():
        async with _server(keys) as handle, _connect(keys, handle.port) as conn:
            await conn.open_connection(LOCALHOST, handle.port)

    with pytest.raises(asyncssh.ChannelOpenError):
        asyncio.run(scenario())


def test_remote_port_forwarding_is_refused(keys):
    async def scenario():
        async with _server(keys) as handle, _connect(keys, handle.port) as conn:
            await conn.forward_remote_port(LOCALHOST, 0, LOCALHOST, handle.port)

    with pytest.raises(asyncssh.ChannelListenError):
        asyncio.run(scenario())


def test_unix_socket_forwarding_is_refused(keys, tmp_path):
    async def scenario():
        async with _server(keys) as handle, _connect(keys, handle.port) as conn:
            await conn.open_unix_connection(str(tmp_path / "otro.sock"))

    with pytest.raises(asyncssh.ChannelOpenError):
        asyncio.run(scenario())


@pytest.fixture
def seen_by_server(monkeypatch):
    """Lo que el servidor ve de cada sesion: socket de agente y pantalla X11."""
    seen = []
    original = service_ssh_server._run_process

    async def spy(process):
        seen.append((process.channel.get_agent_path(), process.channel.get_x11_display()))
        await original(process)

    monkeypatch.setattr(service_ssh_server, "_run_process", spy)
    return seen


def test_agent_forwarding_is_refused(keys, tmp_path, seen_by_server):
    async def scenario():
        async with (
            _server(keys) as handle,
            _connect(
                keys, handle.port, agent_forwarding=True, agent_path=str(tmp_path / "agent.sock")
            ) as conn,
        ):
            return await conn.run("true", check=False)

    assert asyncio.run(scenario()).exit_status == 0
    assert seen_by_server == [(None, None)]


def test_x11_forwarding_is_refused(keys, tmp_path, seen_by_server):
    xauth = tmp_path / "Xauthority"
    xauth.write_bytes(b"")

    async def scenario():
        async with _server(keys) as handle, _connect(keys, handle.port) as conn:
            await conn.run(
                "true",
                x11_forwarding=True,
                x11_display="localhost:99",
                x11_auth_path=str(xauth),
            )

    with pytest.raises(asyncssh.ChannelOpenError, match="X11 forwarding request failed"):
        asyncio.run(scenario())
    assert seen_by_server == []


def test_interactive_shell_is_refused(keys):
    async def scenario():
        async with _server(keys) as handle, _connect(keys, handle.port) as conn:
            return await conn.run(encoding=None, check=False)

    result = asyncio.run(scenario())
    assert result.exit_status == 1


def test_pty_request_is_refused(keys):
    async def scenario():
        async with _server(keys) as handle, _connect(keys, handle.port) as conn:
            await conn.run("true", term_type="xterm")

    with pytest.raises(asyncssh.ChannelOpenError):
        asyncio.run(scenario())
