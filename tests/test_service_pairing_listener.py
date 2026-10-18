"""Ventana de emparejamiento por TCP entre dos instancias locales.

Cada instancia tiene su carpeta de datos en tmp_path; la ventana escucha en
127.0.0.1 con puerto 0. El codigo pasa de un lado al otro dentro del proceso
y nunca se imprime. Incluye las pruebas en negativo (T14).
"""

from __future__ import annotations

import asyncio
import errno

import pytest

from logic._00_logic_pairing import MAX_ATTEMPTS
from services.service_identity import load_or_create_identity
from services.service_paired import load_paired
from services.service_pairing import PairingError, PairingFailure
from services.service_pairing_listener import join_pairing, open_pairing_window

LOCALHOST = "127.0.0.1"
LOOPBACK_NET = "127.0.0.0/8"
CLOSE_TIMEOUT_S = 3


@pytest.fixture
def laptop(tmp_path):
    return load_or_create_identity(tmp_path / "laptop")


@pytest.fixture
def desktop(tmp_path):
    return load_or_create_identity(tmp_path / "desktop")


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


async def _refused(port: int) -> bool:
    try:
        _, writer = await asyncio.open_connection(LOCALHOST, port)
    except ConnectionRefusedError:
        return True
    writer.close()
    return False


def test_right_code_pairs_both_sides_and_closes_port(laptop, desktop):
    async def scenario():
        listener = await open_pairing_window(desktop, LOCALHOST, 0, LOOPBACK_NET)
        joined = await join_pairing(laptop, listener.session.code, LOCALHOST, listener.port)
        shown = await asyncio.wait_for(listener.wait(), CLOSE_TIMEOUT_S)
        return joined, shown, await _refused(listener.port)

    joined, shown, refused = asyncio.run(scenario())
    assert joined.name == desktop.name and shown.name == laptop.name
    assert [p.host_key for p in load_paired(laptop.data_dir)] == [joined.host_key]
    assert [p.user_key for p in load_paired(desktop.data_dir)] == [shown.user_key]
    assert refused


def test_wrong_code_spends_attempts_then_locks(laptop, desktop):
    async def scenario():
        listener = await open_pairing_window(desktop, LOCALHOST, 0, LOOPBACK_NET)
        reasons = []
        for _ in range(MAX_ATTEMPTS):
            with pytest.raises(PairingError) as info:
                await join_pairing(laptop, _wrong(listener.session.code), LOCALHOST, listener.port)
            reasons.append(info.value.reason)
        result = await asyncio.wait_for(listener.wait(), CLOSE_TIMEOUT_S)
        return reasons, result, await _refused(listener.port)

    reasons, result, refused = asyncio.run(scenario())
    assert reasons == [PairingFailure.WRONG_CODE] * MAX_ATTEMPTS
    assert result is None and refused
    assert load_paired(laptop.data_dir) == [] and load_paired(desktop.data_dir) == []


def test_window_expires_and_port_closes(laptop, desktop):
    async def scenario():
        listener = await open_pairing_window(desktop, LOCALHOST, 0, LOOPBACK_NET, window=0.2)
        result = await asyncio.wait_for(listener.wait(), CLOSE_TIMEOUT_S)
        with pytest.raises(ConnectionRefusedError):
            await join_pairing(laptop, listener.session.code, LOCALHOST, listener.port)
        return result

    assert asyncio.run(scenario()) is None
    assert load_paired(desktop.data_dir) == []


def test_origin_outside_network_is_cut_without_spending_attempts(laptop, desktop):
    async def scenario():
        listener = await open_pairing_window(desktop, LOCALHOST, 0, "127.0.0.1/32")
        reader, writer = await asyncio.open_connection(
            LOCALHOST, listener.port, local_addr=("127.0.0.2", 0)
        )
        data = await asyncio.wait_for(reader.read(), CLOSE_TIMEOUT_S)
        writer.close()
        left = listener.session.window.attempts_left
        await listener.close()
        return data, left

    data, left = asyncio.run(scenario())
    assert data == b"" and left == MAX_ATTEMPTS


def test_close_cuts_attempt_in_progress(desktop):
    async def scenario():
        listener = await open_pairing_window(desktop, LOCALHOST, 0, LOOPBACK_NET)
        _, writer = await asyncio.open_connection(LOCALHOST, listener.port)
        await asyncio.sleep(0.05)
        await asyncio.wait_for(listener.close(), CLOSE_TIMEOUT_S)
        writer.close()
        return await asyncio.wait_for(listener.wait(), CLOSE_TIMEOUT_S), listener.port

    result, port = asyncio.run(scenario())
    assert result is None
    assert asyncio.run(_refused(port))


def test_badly_typed_code_fails_before_connecting(laptop):
    with pytest.raises(ValueError):
        asyncio.run(join_pairing(laptop, "12345", LOCALHOST, 9))


def test_refuses_all_interfaces_and_foreign_host(desktop):
    with pytest.raises(ValueError):
        asyncio.run(open_pairing_window(desktop, "0.0.0.0", 0, "0.0.0.0/0"))
    with pytest.raises(ValueError):
        asyncio.run(open_pairing_window(desktop, LOCALHOST, 0, "192.0.2.0/24"))


def test_busy_port_raises_address_in_use(desktop):
    async def scenario():
        first = await open_pairing_window(desktop, LOCALHOST, 0, LOOPBACK_NET)
        try:
            with pytest.raises(OSError) as info:
                await open_pairing_window(desktop, LOCALHOST, first.port, LOOPBACK_NET)
            return info.value.errno
        finally:
            await first.close()

    assert asyncio.run(scenario()) == errno.EADDRINUSE
