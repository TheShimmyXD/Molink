"""Modo de ensayo del servidor: el programa real y el ssh de OpenSSH.

El cliente es el mismo ssh que se usara en la sobremesa, aislado de ~/.ssh:
sin config, sin agente, solo la llave de tmp_path y un known_hosts propio.
"""

from __future__ import annotations

import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from services.service_identity import load_or_create_key
from services.service_ssh_server import check_listen_host

LOCALHOST = "127.0.0.1"
SERVER_SCRIPT = Path(__file__).resolve().parents[1] / "services" / "service_ssh_server.py"


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_all_interfaces_are_rejected(host):
    with pytest.raises(ValueError):
        check_listen_host(host)


def test_hostname_is_not_an_ip():
    with pytest.raises(ValueError):
        check_listen_host("localhost")


def test_concrete_ip_is_accepted():
    assert check_listen_host(LOCALHOST) == LOCALHOST


@pytest.mark.linux_only
def test_host_key_is_created_private_and_reused(tmp_path):
    path = tmp_path / "data" / "host_key"
    first = load_or_create_key(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert load_or_create_key(path).public_data == first.public_data


def _free_port():
    with socket.socket() as sock:
        sock.bind((LOCALHOST, 0))
        return sock.getsockname()[1]


def _ssh_args(tmp_path, port, known_hosts):
    return [
        "ssh",
        "-F", "/dev/null",
        "-i", str(tmp_path / "client"),
        "-p", str(port),
        "-o", "IdentitiesOnly=yes",
        "-o", "IdentityAgent=none",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", "GlobalKnownHostsFile=/dev/null",
        f"molink@{LOCALHOST}",
    ]  # fmt: skip


@pytest.mark.skipif(shutil.which("ssh") is None, reason="falta el cliente ssh de OpenSSH")
@pytest.mark.linux_only
def test_openssh_client_runs_hostname(tmp_path):
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "client")], check=True
    )
    port = _free_port()
    data = tmp_path / "data"
    server = subprocess.Popen(
        [sys.executable, str(SERVER_SCRIPT), "--host", LOCALHOST, "--port", str(port)]
        + ["--network", "127.0.0.0/8"]
        + ["--data", str(data), "--allow", str(tmp_path / "client.pub")],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert server.stdout.readline().startswith(f"Escuchando en {LOCALHOST}:{port}")
        host_pub = load_or_create_key(data / "host_key").export_public_key().decode()
        known_hosts = tmp_path / "known_hosts"
        known_hosts.write_text(f"[{LOCALHOST}]:{port} {host_pub}")
        done = subprocess.run(
            _ssh_args(tmp_path, port, known_hosts) + ["hostname"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert done.returncode == 0
        assert done.stdout.strip() == socket.gethostname()
    finally:
        server.send_signal(signal.SIGTERM)
        assert server.wait(timeout=10) == 0
    with socket.socket() as sock:
        assert sock.connect_ex((LOCALHOST, port)) != 0


@pytest.mark.linux_only
def test_keepalive_drops_a_frozen_server(tmp_path, monkeypatch):
    """Servidor congelado (SIGSTOP), como si la red se fuera sin cerrar el TCP:
    el cliente suelta la conexion por keepalive en vez de quedar colgado."""
    import asyncio
    import time

    import asyncssh

    from services import service_ssh_client

    monkeypatch.setattr(service_ssh_client, "KEEPALIVE_S", 0.2)
    monkeypatch.setattr(service_ssh_client, "KEEPALIVE_MISSES", 2)
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "client")], check=True
    )
    port = _free_port()
    data = tmp_path / "data"
    server = subprocess.Popen(
        [sys.executable, str(SERVER_SCRIPT), "--host", LOCALHOST, "--port", str(port)]
        + ["--network", "127.0.0.0/8"]
        + ["--data", str(data), "--allow", str(tmp_path / "client.pub")],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    async def frozen_peer() -> float:
        client_key = asyncssh.read_private_key(str(tmp_path / "client"))
        host_key = load_or_create_key(data / "host_key").convert_to_public()
        async with service_ssh_client.connect_peer(LOCALHOST, port, client_key, host_key) as conn:
            server.send_signal(signal.SIGSTOP)
            start = time.monotonic()
            await asyncio.wait_for(conn.wait_closed(), timeout=10)
            return time.monotonic() - start

    try:
        assert server.stdout.readline().startswith(f"Escuchando en {LOCALHOST}:{port}")
        assert asyncio.run(frozen_peer()) < 2.0
    finally:
        server.send_signal(signal.SIGCONT)
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=10)
