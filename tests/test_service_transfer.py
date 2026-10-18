"""Pasar archivos: dos instancias en 127.0.0.1 con llaves y carpetas en tmp_path.

El archivo de prueba se genera con bytes al azar y se compara por sha256;
nunca se imprime. Las pruebas negativas (T14) cubren lo que el SFTP de llegada
rechaza: escribir algo que no sea .part, pisar un archivo, renombrar con
reemplazo, borrar lo recibido, crear carpetas o enlaces y salir de la carpeta.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from contextlib import asynccontextmanager

import asyncssh
import pytest

from services import service_transfer
from services.service_discovery import Peer
from services.service_identity import load_or_create_identity, save_device_name
from services.service_link import LinkError, LinkSession, LinkSettings
from services.service_ssh_server import start_server
from services.service_transfer import (
    ALREADY_EXISTS,
    TransferStalled,
    candidate_names,
    default_inbox,
    send_file,
)

LOCALHOST = "127.0.0.1"
LOOPBACK_NET = "127.0.0.0/8"
MB = 1024 * 1024


def _make_key(tmp_path, name):
    path = tmp_path / name
    asyncssh.generate_private_key("ssh-ed25519").write_private_key(str(path))
    path.chmod(0o600)
    return asyncssh.read_private_key(str(path))


def _random_file(path, size):
    path.write_bytes(os.urandom(size))
    return path


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def keys(tmp_path):
    return {name: _make_key(tmp_path, name) for name in ("host", "paired")}


@asynccontextmanager
async def _connected(keys, inbox, on_incoming=None):
    handle = await start_server(
        LOCALHOST, 0, keys["host"], lambda: [keys["paired"]], LOOPBACK_NET, inbox, on_incoming
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


def test_file_arrives_with_same_sha256_and_no_part_left(tmp_path, keys):
    source = _random_file(tmp_path / "prueba.bin", 3 * MB + 17)
    inbox = tmp_path / "llegada"
    progress: list[tuple[int, int]] = []

    async def scenario():
        async with _connected(keys, inbox) as conn:
            return await send_file(conn, source, lambda *p: progress.append(p))

    assert asyncio.run(scenario()) == "prueba.bin"
    assert sorted(p.name for p in inbox.iterdir()) == ["prueba.bin"]
    assert _sha256(inbox / "prueba.bin") == _sha256(source)
    assert progress[-1] == (source.stat().st_size, source.stat().st_size)


def test_existing_name_is_never_overwritten(tmp_path, keys):
    inbox = tmp_path / "llegada"
    inbox.mkdir()
    kept = _random_file(inbox / "notas.txt", 100)
    kept_sha = _sha256(kept)
    _random_file(inbox / "notas (1).txt.part", 10)  # un envio a medias toma ese nombre
    source = _random_file(tmp_path / "notas.txt", 2000)

    async def scenario():
        async with _connected(keys, inbox) as conn:
            return [await send_file(conn, source), await send_file(conn, source)]

    assert asyncio.run(scenario()) == ["notas (2).txt", "notas (3).txt"]
    assert _sha256(kept) == kept_sha
    assert _sha256(inbox / "notas (2).txt") == _sha256(source)


def test_candidate_names_keep_the_extension():
    names = candidate_names("foto.tar.gz")
    assert [next(names) for _ in range(3)] == ["foto.tar.gz", "foto.tar (1).gz", "foto.tar (2).gz"]
    assert next(candidate_names("LEEME")) == "LEEME"


def test_cancel_removes_the_part(tmp_path, keys):
    source = _random_file(tmp_path / "grande.bin", 32 * MB)
    inbox = tmp_path / "llegada"

    async def scenario():
        async with _connected(keys, inbox) as conn:
            started = asyncio.Event()
            task = asyncio.create_task(send_file(conn, source, lambda *_: started.set()))
            await asyncio.wait_for(started.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    assert list(inbox.iterdir()) == []


def test_inbox_rejects_everything_but_new_parts(tmp_path, keys):
    inbox = tmp_path / "llegada"
    inbox.mkdir()
    _random_file(inbox / "recibido.txt", 50)
    _random_file(inbox / "otro.part", 5)
    outside = tmp_path / "fuera.part"

    async def scenario():
        async with _connected(keys, inbox) as conn, conn.start_sftp_client() as sftp:
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.open("nuevo.txt", "wb")
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.open("recibido.txt", "ab")
            with pytest.raises(asyncssh.SFTPError, match=ALREADY_EXISTS):
                await sftp.open("otro.part", "wb")
            with pytest.raises(asyncssh.SFTPError, match=ALREADY_EXISTS):
                await sftp.rename("otro.part", "recibido.txt")
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.posix_rename("otro.part", "recibido.txt")
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.rename("recibido.txt", "copia.part")
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.remove("recibido.txt")
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.mkdir("carpeta")
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.symlink("/etc/passwd", "enlace")
            with pytest.raises(asyncssh.SFTPPermissionDenied):
                await sftp.chmod("recibido.txt", 0o777)
            # ../ no sale de la carpeta: el chroot lo deja dentro.
            async with sftp.open("../fuera.part", "wb") as handle:
                await handle.write(b"x")
            await sftp.remove("otro.part")

    asyncio.run(scenario())
    assert not outside.exists()
    assert sorted(p.name for p in inbox.iterdir()) == ["fuera.part", "recibido.txt"]


def test_server_without_inbox_has_no_sftp(tmp_path, keys):
    source = _random_file(tmp_path / "prueba.bin", 10)

    async def scenario():
        async with _connected(keys, None) as conn:
            with pytest.raises((asyncssh.ChannelOpenError, asyncssh.SFTPError, OSError)):
                await send_file(conn, source)

    asyncio.run(scenario())


def test_default_inbox_follows_user_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    dirs = tmp_path / "user-dirs.dirs"
    dirs.write_text('# comentario\nXDG_DOWNLOAD_DIR="$HOME/Descargas"\n', encoding="utf-8")
    assert default_inbox(dirs) == tmp_path / "Descargas" / "Molink"
    assert default_inbox(tmp_path / "no-existe") == tmp_path / "Downloads" / "Molink"


def _identity(tmp_path, name):
    save_device_name(tmp_path / name, name)
    return load_or_create_identity(tmp_path / name)


def test_link_send_between_two_paired_instances(tmp_path):
    a, b = _identity(tmp_path, "equipo-a"), _identity(tmp_path, "equipo-b")
    inbox_a = tmp_path / "llegada-a"
    source = _random_file(tmp_path / "hacia-a.bin", MB)
    seen: list[Peer] = []

    async def browse(host, own_name, seconds, subnet):
        return list(seen), 0.0

    async def scenario():
        shower = LinkSession(
            a, LinkSettings(LOCALHOST, 0, 0, LOOPBACK_NET, announce=False, inbox=inbox_a), browse
        )
        joiner = LinkSession(b, LinkSettings(LOCALHOST, 0, 0, LOOPBACK_NET, announce=False), browse)
        await shower.start()
        await joiner.start()
        try:
            window = await shower.open_window()
            waiting = asyncio.create_task(shower.wait_window())
            await joiner.join(window.code, LOCALHOST, window.port)
            await waiting
            seen.append(Peer("equipo-a", LOCALHOST, shower.ssh_port))
            await joiner.browse()
            with pytest.raises(LinkError, match="No se encontró"):
                await joiner.send("equipo-a", tmp_path / "no-existe.bin", lambda *_: None)
            first = await joiner.send("equipo-a", source, lambda *_: None)
            second = await joiner.send("equipo-a", source, lambda *_: None)
            # b no tiene carpeta de llegada: no recibe archivos.
            seen.append(Peer("equipo-b", LOCALHOST, joiner.ssh_port))
            await shower.browse()
            with pytest.raises(LinkError, match="no recibe archivos"):
                await shower.send("equipo-b", source, lambda *_: None)
            return first, second
        finally:
            await shower.close()
            await joiner.close()

    assert asyncio.run(scenario()) == ("hacia-a.bin", "hacia-a (1).bin")
    assert _sha256(inbox_a / "hacia-a (1).bin") == _sha256(source)


def test_two_sends_at_once_get_different_names(tmp_path, keys):
    inbox = tmp_path / "llegada"
    (tmp_path / "uno").mkdir()
    (tmp_path / "dos").mkdir()
    first = _random_file(tmp_path / "uno" / "dato.bin", 2 * MB)
    second = _random_file(tmp_path / "dos" / "dato.bin", 2 * MB)

    async def scenario():
        async with _connected(keys, inbox) as conn:
            return await asyncio.gather(send_file(conn, first), send_file(conn, second))

    names = asyncio.run(scenario())
    assert sorted(names) == ["dato (1).bin", "dato.bin"]
    arrived = {_sha256(inbox / name) for name in names}
    assert arrived == {_sha256(first), _sha256(second)}
    assert sorted(p.name for p in inbox.iterdir()) == sorted(names)


def test_progress_moves_in_small_blocks(tmp_path, keys):
    source = _random_file(tmp_path / "medio.bin", 2 * MB)
    progress: list[tuple[int, int]] = []

    async def scenario():
        async with _connected(keys, tmp_path / "llegada") as conn:
            await send_file(conn, source, lambda *p: progress.append(p))

    asyncio.run(scenario())
    # 2 MiB en bloques de 256 KiB: al menos 8 avisos, no uno solo de 4 MiB.
    assert len([p for p in progress if p[0] > 0]) >= 2 * MB // service_transfer.BLOCK_SIZE


def test_stalled_send_is_cut(tmp_path, keys, monkeypatch):
    source = _random_file(tmp_path / "trabado.bin", MB)
    monkeypatch.setattr(service_transfer, "CHECK_S", 0.05)
    monkeypatch.setattr(service_transfer, "REMOVE_TIMEOUT_S", 0.2)

    async def never_writes(self, file_obj, offset, data):
        await asyncio.sleep(3600)

    monkeypatch.setattr(service_transfer.InboxSFTPServer, "write", never_writes)

    async def scenario():
        async with _connected(keys, tmp_path / "llegada") as conn:
            started = time.monotonic()
            with pytest.raises(TransferStalled):
                await send_file(conn, source, stall_s=0.3)
            return time.monotonic() - started

    assert asyncio.run(scenario()) < 3
