"""Emparejamiento SPAKE2: codigo correcto, erroneo, caducado e intermediario.

Los codigos son fijos de prueba (randbelow falso); las llaves se crean en
tmp_path. Ningun codigo ni llave privada sale de la prueba.
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from logic._00_logic_pairing import MAX_ATTEMPTS, WINDOW_SECONDS, PairingState
from services.service_identity import load_or_create_identity
from services.service_paired import PeerRecord, add_paired, authorized_user_keys
from services.service_pairing import (
    MAX_FRAME,
    ChannelClosed,
    PairingError,
    PairingFailure,
    PairingSession,
    StreamChannel,
    pair_as_joiner,
    pair_as_shower,
)

LOCALHOST = "127.0.0.1"


class MemoryChannel:
    """Un extremo de un canal en memoria; close() hace que el otro vea EOF."""

    def __init__(self, inbox: asyncio.Queue, outbox: asyncio.Queue):
        self._inbox = inbox
        self._outbox = outbox

    async def send(self, data: bytes) -> None:
        await self._outbox.put(data)

    async def recv(self) -> bytes:
        data = await self._inbox.get()
        if data is None:
            raise ChannelClosed
        return data

    def close(self) -> None:
        self._outbox.put_nowait(None)


def channel_pair() -> tuple[MemoryChannel, MemoryChannel]:
    a_to_b, b_to_a = asyncio.Queue(), asyncio.Queue()
    return MemoryChannel(b_to_a, a_to_b), MemoryChannel(a_to_b, b_to_a)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def fixed(code: str):
    return lambda _n: int(code)


def peer_of(tmp_path, name: str) -> PeerRecord:
    identity = load_or_create_identity(tmp_path / name)
    return PeerRecord.build(
        name,
        identity.user_key.export_public_key().decode(),
        identity.host_key.export_public_key().decode(),
    )


@pytest.fixture
def laptop(tmp_path):
    return peer_of(tmp_path, "laptop")


@pytest.fixture
def desktop(tmp_path):
    return peer_of(tmp_path, "sobremesa")


async def _closing(coro, channel: MemoryChannel):
    """Como en la app: al terminar un lado, su canal se cierra."""
    try:
        return await coro
    finally:
        channel.close()


async def run_pair(session, typed_code, shower, joiner):
    side_shower, side_joiner = channel_pair()
    return await asyncio.gather(
        _closing(pair_as_shower(session, side_shower, shower), side_shower),
        _closing(pair_as_joiner(typed_code, side_joiner, joiner), side_joiner),
        return_exceptions=True,
    )


def reason(result) -> PairingFailure:
    assert isinstance(result, PairingError), result
    return result.reason


# -- Codigo correcto ---------------------------------------------


def test_right_code_pairs_both_sides(laptop, desktop, tmp_path):
    session = PairingSession(clock=Clock(), randbelow=fixed("042517"))
    got_by_laptop, got_by_desktop = asyncio.run(run_pair(session, "042 517", laptop, desktop))
    assert got_by_laptop == desktop
    assert got_by_desktop == laptop
    assert session.state() is PairingState.PAIRED
    add_paired(tmp_path / "laptop", got_by_laptop)
    allowed = authorized_user_keys(tmp_path / "laptop")
    assert [key.export_public_key().decode().split()[1] for key in allowed] == [
        desktop.user_key.split()[1]
    ]


def test_right_code_pairs_over_tcp(laptop, desktop):
    async def scenario():
        session = PairingSession(clock=Clock(), randbelow=fixed("314159"))
        done: asyncio.Future = asyncio.get_running_loop().create_future()

        async def handle(reader, writer):
            try:
                done.set_result(
                    await pair_as_shower(session, StreamChannel(reader, writer), laptop)
                )
            except Exception as exc:  # la prueba lo revisa abajo
                done.set_exception(exc)
            finally:
                writer.close()

        server = await asyncio.start_server(handle, LOCALHOST, 0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection(LOCALHOST, port)
            got_by_desktop = await pair_as_joiner("314159", StreamChannel(reader, writer), desktop)
            writer.close()
            return await done, got_by_desktop
        finally:
            server.close()
            await server.wait_closed()

    got_by_laptop, got_by_desktop = asyncio.run(scenario())
    assert got_by_laptop == desktop
    assert got_by_desktop == laptop


# -- Codigo erroneo y limite de intentos --------------------------


def test_wrong_code_fails_on_both_sides(laptop, desktop):
    session = PairingSession(clock=Clock(), randbelow=fixed("111111"))
    shower, joiner = asyncio.run(run_pair(session, "111112", laptop, desktop))
    assert reason(shower) is PairingFailure.WRONG_CODE
    assert reason(joiner) is PairingFailure.WRONG_CODE
    assert session.window.attempts_left == MAX_ATTEMPTS - 1
    assert session.state() is PairingState.OPEN


def test_attempts_run_out_then_right_code_is_refused(laptop, desktop):
    session = PairingSession(clock=Clock(), randbelow=fixed("111111"))
    for guess in ["000001", "000002", "000003"][:MAX_ATTEMPTS]:
        asyncio.run(run_pair(session, guess, laptop, desktop))
    assert session.state() is PairingState.LOCKED
    shower, joiner = asyncio.run(run_pair(session, "111111", laptop, desktop))
    assert reason(shower) is PairingFailure.LOCKED
    assert reason(joiner) is PairingFailure.LOCKED


# -- Codigo caducado ---------------------------------------------


def test_expired_code_is_refused_without_spending_attempts(laptop, desktop):
    clock = Clock()
    session = PairingSession(clock=clock, randbelow=fixed("271828"))
    clock.now += WINDOW_SECONDS + 1
    shower, joiner = asyncio.run(run_pair(session, "271828", laptop, desktop))
    assert reason(shower) is PairingFailure.EXPIRED
    assert reason(joiner) is PairingFailure.EXPIRED
    assert session.window.attempts_left == MAX_ATTEMPTS


def test_code_cannot_be_reused_after_pairing(laptop, desktop, tmp_path):
    session = PairingSession(clock=Clock(), randbelow=fixed("161803"))
    asyncio.run(run_pair(session, "161803", laptop, desktop))
    other = peer_of(tmp_path, "tercero")
    shower, joiner = asyncio.run(run_pair(session, "161803", laptop, other))
    assert reason(joiner) is PairingFailure.CLOSED


# -- Intermediario sin el codigo ----------------------------------


def test_man_in_the_middle_without_code_fails(laptop, desktop, tmp_path):
    """M se hace pasar por la sobremesa ante la laptop y por la laptop ante la sobremesa."""
    attacker = peer_of(tmp_path, "intruso")

    async def scenario():
        real_session = PairingSession(clock=Clock(), randbelow=fixed("555123"))
        fake_session = PairingSession(clock=Clock(), randbelow=fixed("000000"))
        a_laptop, a_attacker = channel_pair()
        b_attacker, b_desktop = channel_pair()
        return await asyncio.gather(
            _closing(pair_as_shower(real_session, a_laptop, laptop), a_laptop),
            _closing(pair_as_joiner("123456", a_attacker, attacker), a_attacker),
            _closing(pair_as_shower(fake_session, b_attacker, attacker), b_attacker),
            _closing(pair_as_joiner("555123", b_desktop, desktop), b_desktop),
            return_exceptions=True,
        )

    laptop_side, _, _, desktop_side = asyncio.run(scenario())
    assert reason(laptop_side) is PairingFailure.WRONG_CODE
    assert reason(desktop_side) is PairingFailure.WRONG_CODE


def _swap_keys(data: bytes, attacker: PeerRecord) -> bytes:
    """Cambia el payload firmado por uno con las llaves del intruso."""
    message = json.loads(data)
    if "payload" not in message:
        return data
    payload = json.loads(base64.b64decode(message["payload"]))
    payload["user_key"], payload["host_key"] = attacker.user_key, attacker.host_key
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    message["payload"] = base64.b64encode(raw).decode()
    return json.dumps(message).encode()


@pytest.mark.parametrize("tampered", [1, 2])  # mensaje 2 (hacia el joiner) o 3 (hacia el shower)
def test_relay_that_swaps_keys_is_detected(laptop, desktop, tmp_path, tampered):
    attacker = peer_of(tmp_path, "intruso")

    async def relay(src: MemoryChannel, dst: MemoryChannel, counter: list[int]):
        while True:
            try:
                data = await src.recv()
            except ChannelClosed:
                dst.close()
                return
            index = counter[0]
            counter[0] += 1
            await dst.send(_swap_keys(data, attacker) if index == tampered else data)

    async def scenario():
        session = PairingSession(clock=Clock(), randbelow=fixed("909090"))
        laptop_end, relay_a = channel_pair()
        relay_b, desktop_end = channel_pair()
        counter = [0]
        relays = [
            asyncio.create_task(relay(relay_a, relay_b, counter)),
            asyncio.create_task(relay(relay_b, relay_a, counter)),
        ]
        results = await asyncio.gather(
            _closing(pair_as_shower(session, laptop_end, laptop), laptop_end),
            _closing(pair_as_joiner("909090", desktop_end, desktop), desktop_end),
            return_exceptions=True,
        )
        for task in relays:
            task.cancel()
        return results

    shower, joiner = asyncio.run(scenario())
    assert reason(shower) is PairingFailure.WRONG_CODE
    assert reason(joiner) is PairingFailure.WRONG_CODE


# -- Mensajes invalidos --------------------------------------------


def test_same_machine_on_both_sides_is_refused(laptop):
    session = PairingSession(clock=Clock(), randbelow=fixed("123123"))
    shower, joiner = asyncio.run(run_pair(session, "123123", laptop, laptop))
    assert reason(joiner) is PairingFailure.PROTOCOL


@pytest.mark.parametrize("first", [b"no es json", b"[]", b'{"v": 2, "spake": ""}', b'{"v": 1}'])
def test_garbage_first_message_is_refused(laptop, first):
    async def scenario():
        session = PairingSession(clock=Clock(), randbelow=fixed("123123"))
        side, other = channel_pair()
        await other.send(first)
        with pytest.raises(PairingError) as info:
            await pair_as_shower(session, side, laptop)
        return info.value.reason

    assert asyncio.run(scenario()) is PairingFailure.PROTOCOL


def test_oversized_frame_is_refused():
    async def scenario():
        reader = asyncio.StreamReader()
        reader.feed_data((MAX_FRAME + 1).to_bytes(4, "big"))
        with pytest.raises(PairingError) as info:
            await StreamChannel(reader, writer=None, timeout=1).recv()  # type: ignore[arg-type]
        return info.value.reason

    assert asyncio.run(scenario()) is PairingFailure.PROTOCOL


def test_silent_peer_times_out():
    async def scenario():
        reader = asyncio.StreamReader()
        with pytest.raises(PairingError) as info:
            await StreamChannel(reader, writer=None, timeout=0.05).recv()  # type: ignore[arg-type]
        return info.value.reason

    assert asyncio.run(scenario()) is PairingFailure.TIMEOUT
