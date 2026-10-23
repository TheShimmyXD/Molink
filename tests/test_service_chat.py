"""Chat: un servidor en 127.0.0.1 y un cliente emparejado, llaves en tmp_path.

Los mensajes de prueba son textos inventados; se comparan en memoria y nunca
se imprimen. Las pruebas negativas (T14) cubren lo que el subsistema de chat
rechaza: linea demasiado larga, algo que no es JSON, campos que faltan y un
servidor que no escucha el chat.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import asyncssh
import pytest

from services.service_chat import CHAT_SUBSYSTEM, MAX_LINE, ChatChannel
from services.service_ssh_server import start_server
from tests.test_service_transfer import LOCALHOST, LOOPBACK_NET, _make_key


@pytest.fixture
def keys(tmp_path):
    return {name: _make_key(tmp_path, name) for name in ("host", "paired")}


@asynccontextmanager
async def _connected(keys, on_message):
    handle = await start_server(
        LOCALHOST, 0, keys["host"], lambda: [keys["paired"]], LOOPBACK_NET, on_message=on_message
    )
    try:
        async with asyncssh.connect(
            LOCALHOST,
            handle.port,
            username="molink",
            client_keys=[keys["paired"]],
            known_hosts=([keys["host"].convert_to_public()], [], []),
            agent_path=None,
            config=None,
        ) as conn:
            yield conn
    finally:
        await handle.close()


def test_messages_arrive_in_order_with_their_ack(tmp_path, keys, caplog):
    texts = ["hola", "¿qué tal? ñandú 🚀", "línea uno\nlínea dos"]
    received = []

    async def scenario():
        async with _connected(keys, received.append) as conn:
            channel = await ChatChannel.open(conn)
            ids = [await channel.send(text) for text in texts]
            await channel.close()
            return ids

    with caplog.at_level(logging.DEBUG):
        ids = asyncio.run(scenario())
    assert [m.text for m in received] == texts
    assert [m.message_id for m in received] == ids
    assert {m.peer_key for m in received} == {keys["paired"].public_data}
    ours = [r.getMessage() for r in caplog.records if not r.name.startswith("asyncssh")]
    assert not [m for m in ours if "hola" in m or "ñandú" in m]


def test_many_sends_at_once_all_get_their_ack(tmp_path, keys):
    received = []

    async def scenario():
        async with _connected(keys, received.append) as conn:
            channel = await ChatChannel.open(conn)
            ids = await asyncio.gather(*(channel.send(f"m{i}") for i in range(30)))
            await channel.close()
            return ids

    ids = asyncio.run(scenario())
    assert len(set(ids)) == 30
    assert sorted(m.message_id for m in received) == sorted(ids)


def test_too_long_message_is_refused_before_sending(tmp_path, keys):
    received = []

    async def scenario():
        async with _connected(keys, received.append) as conn:
            channel = await ChatChannel.open(conn)
            with pytest.raises(ValueError):
                await channel.send("x" * MAX_LINE)
            # El canal sigue sirviendo.
            await channel.send("corto")
            await channel.close()

    asyncio.run(scenario())
    assert [m.text for m in received] == ["corto"]


@pytest.mark.parametrize(
    "raw",
    [
        b"x" * (MAX_LINE + 10),  # sin fin de linea y mas largo que MAX_LINE
        b"no es json\n",
        b'{"id": "1"}\n',  # falta text
        b'{"id": 1, "text": "hola"}\n',  # id que no es texto
        b'["id", "text"]\n',
    ],
    ids=["larga", "no-json", "sin-text", "id-numerico", "lista"],
)
def test_chat_closes_on_anything_that_is_not_a_message(tmp_path, keys, raw):
    received = []

    async def scenario():
        async with _connected(keys, received.append) as conn:
            process = await conn.create_process(subsystem=CHAT_SUBSYSTEM, encoding=None)
            process.stdin.write(raw)
            await asyncio.wait_for(process.wait_closed(), 5)
            return process.exit_status

    assert asyncio.run(scenario()) == 1
    assert received == []


def test_server_without_chat_refuses_the_subsystem(tmp_path, keys):
    async def scenario():
        async with _connected(keys, None) as conn:
            channel = await ChatChannel.open(conn)
            with pytest.raises(ConnectionError):
                await channel.send("nadie escucha", timeout=5)
            await channel.close()
            return channel.process.exit_status

    assert asyncio.run(scenario()) == 1


def test_send_after_the_other_side_leaves_fails_clearly(tmp_path, keys):
    async def scenario():
        async with _connected(keys, lambda _m: None) as conn:
            channel = await ChatChannel.open(conn)
            await channel.send("antes")
            conn.abort()
            await asyncio.wait_for(asyncio.shield(channel._reader), 5)
            with pytest.raises(ConnectionError):
                await channel.send("despues")

    asyncio.run(scenario())


def test_app_failure_leaves_the_message_without_ack(tmp_path, keys):
    def broken(message):
        if message.text == "falla":
            raise RuntimeError("la app no lo pudo mostrar")

    async def scenario():
        async with _connected(keys, broken) as conn:
            channel = await ChatChannel.open(conn)
            with pytest.raises(TimeoutError):
                await channel.send("falla", timeout=0.5)
            await channel.send("sigue")
            await channel.close()

    asyncio.run(scenario())
