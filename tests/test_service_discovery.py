"""Descubrimiento con zeroconf: la conversion pura y un ensayo de dos procesos en 127.0.0.1."""

from __future__ import annotations

import asyncio
import ipaddress
import signal
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from services.service_discovery import SERVICE_TYPE, Announcer, Peer, browse, peer_from_info

LOCALHOST = "127.0.0.1"
SUBNET = ipaddress.ip_network("192.0.2.0/24")
DISCOVERY_SCRIPT = Path(__file__).resolve().parents[1] / "services" / "service_discovery.py"


def test_peer_is_built_from_announcement():
    peer = peer_from_info(f"otro.{SERVICE_TYPE}", ["192.0.2.7"], 47820, "yo", SUBNET)
    assert peer == Peer("otro", "192.0.2.7", 47820)


def test_own_announcement_is_ignored():
    assert peer_from_info(f"yo.{SERVICE_TYPE}", ["192.0.2.7"], 47820, "yo", SUBNET) is None


def test_address_outside_subnet_is_ignored():
    assert peer_from_info(f"otro.{SERVICE_TYPE}", ["198.51.100.3"], 47820, "yo", SUBNET) is None


def test_first_address_inside_subnet_is_chosen():
    addresses = ["198.51.100.3", "192.0.2.9"]
    peer = peer_from_info(f"otro.{SERVICE_TYPE}", addresses, 47820, "yo", SUBNET)
    assert peer.address == "192.0.2.9"


def test_announcement_without_port_is_ignored():
    assert peer_from_info(f"otro.{SERVICE_TYPE}", ["192.0.2.7"], None, "yo", SUBNET) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_all_interfaces_are_rejected(host):
    with pytest.raises(ValueError):
        Announcer("yo", host, 47820)


def _unique_name(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.mark.linux_only
def test_two_processes_find_each_other_and_close_cleanly():
    name = _unique_name("ensayo")
    announcer = subprocess.Popen(
        [sys.executable, str(DISCOVERY_SCRIPT), "announce", "--host", LOCALHOST]
        + ["--name", name, "--port", "47831"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert announcer.stdout.readline().startswith(f"Anunciando {name}")
        peers, first = asyncio.run(browse(LOCALHOST, _unique_name("buscador"), 2.0))
    finally:
        announcer.send_signal(signal.SIGTERM)
        assert announcer.wait(timeout=10) == 0
    assert Peer(name, LOCALHOST, 47831) in peers
    assert first is not None and first < 2.0
    # Al cerrar la app el anuncio se retira: otra busqueda ya no lo ve.
    peers_after, _ = asyncio.run(browse(LOCALHOST, _unique_name("buscador"), 1.5))
    assert all(peer.name != name for peer in peers_after)


def test_peer_os_comes_from_announcement():
    name = f"otro.{SERVICE_TYPE}"
    windows = peer_from_info(name, ["192.0.2.7"], 47820, "yo", SUBNET, {b"os": b"windows"})
    old = peer_from_info(name, ["192.0.2.7"], 47820, "yo", SUBNET, {b"v": b"1"})
    assert windows.os == "windows"
    assert old.os == "linux"
