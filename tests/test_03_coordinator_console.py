"""Coordinador de la consola: dos instancias locales con el bucle de red real.

Se emparejan con sus coordinadores de emparejar (como en la app) y la consola
de b usa el mismo enlace de b. Cada una con su carpeta en tmp_path y puertos
libres de 127.0.0.1, sin anuncio; la busqueda es falsa y devuelve el puerto
real de a.
"""

from __future__ import annotations

import os
import socket
import subprocess

import pytest

from core.async_loop import AsyncLoop
from modules.mod_02_pair._02_coordinator import PairCoordinator
from modules.mod_03_console._03_coordinator import ConsoleCoordinator
from services.service_discovery import Peer
from services.service_identity import load_or_create_identity, save_device_name
from services.service_link import LinkSession, LinkSettings
from tests.test_02_coordinator_pair import LOCALHOST, LOOPBACK_NET, _free_port, _wait_until

LONG_SLEEP = "sleep 31.5"  # unico, para buscarlo con pgrep


class _Node:
    def __init__(self, loop, tmp_path, name, pair_port, seen):
        save_device_name(tmp_path / name, name)
        identity = load_or_create_identity(tmp_path / name)
        settings = LinkSettings(LOCALHOST, 0, pair_port, LOOPBACK_NET, announce=False)

        async def browse(host, own_name, seconds, subnet):
            return list(seen), 0.0

        self.link = LinkSession(identity, settings, browse)
        self.pair = PairCoordinator(loop, self.link, lambda: LOCALHOST, browse_every_ms=100)
        self.console = ConsoleCoordinator(loop, self.link, refresh_every_ms=100)
        self.pair_views: list[dict] = []
        self.views: list[dict] = []
        self.output: list[str] = []
        self.pair.view_changed.connect(self.pair_views.append)
        self.console.view_changed.connect(self.views.append)
        self.console.output_added.connect(self.output.append)

    @property
    def view(self) -> dict:
        return self.views[-1]

    @property
    def text(self) -> str:
        return "".join(self.output)


@pytest.fixture
def loop():
    loop = AsyncLoop()
    yield loop
    loop.stop()


def _remote_sleep_alive() -> bool:
    return subprocess.run(["pgrep", "-f", LONG_SLEEP], capture_output=True).returncode == 0


def _paired(qt_application, loop, tmp_path):
    """a y b emparejados; la consola de b ya ve a a."""
    pair_port = _free_port()
    seen: list[Peer] = []
    a = _Node(loop, tmp_path, "equipo-a", pair_port, [])
    b = _Node(loop, tmp_path, "equipo-b", pair_port, seen)
    a.pair.start()
    b.pair.start()
    b.console.start()
    _wait_until(qt_application, lambda: a.pair_views[-1]["state"] == "ONLINE")
    seen.append(Peer("equipo-a", LOCALHOST, a.link.ssh_port))
    _wait_until(qt_application, lambda: b.views and b.view["state"] == "NO_TARGET")

    a.pair.open_window()
    _wait_until(qt_application, lambda: a.pair_views[-1]["window_open"])
    _wait_until(
        qt_application, lambda: [r.address for r in b.pair_views[-1]["rows"]] == [LOCALHOST]
    )
    b.pair.join("equipo-a", a.pair_views[-1]["code"])
    _wait_until(qt_application, lambda: b.view["targets"] == [("equipo-a", LOCALHOST)])
    return a, b, pair_port


def _close(a, b, pair_port):
    b.console.close()
    b.pair.close()
    a.pair.close()
    with socket.socket() as sock:
        assert sock.connect_ex((LOCALHOST, pair_port)) != 0


@pytest.mark.linux_only
def test_run_live_output_and_cancel_between_two_instances(qt_application, loop, tmp_path):
    a, b, pair_port = _paired(qt_application, loop, tmp_path)
    b.console.run("printf 'hola\\n'; printf 'ñu' >&2; exit 4")
    assert b.view["running"]
    _wait_until(qt_application, lambda: not b.view["running"])
    assert b.view["outcome"].text.startswith("Terminó con código 4 en ")
    assert b.text.startswith("~ $ printf") and "hola\n" in b.text and "ñu" in b.text

    b.console.run(f"echo listo; {LONG_SLEEP}")
    _wait_until(qt_application, lambda: b.text.endswith("listo\n"))
    assert b.text.count("\n~ $ ") == 1  # el eco empieza en linea nueva
    _wait_until(qt_application, _remote_sleep_alive)
    b.console.cancel()
    assert b.view["outcome"].text.startswith("Cancelado a los ") and not b.view["running"]
    _wait_until(qt_application, lambda: not _remote_sleep_alive(), timeout=4.0)
    _close(a, b, pair_port)


@pytest.mark.linux_only
def test_folder_follows_cd_and_sudo_gets_the_password(qt_application, loop, tmp_path, monkeypatch):
    """La carpeta sigue al cd entre comandos y sudo lee la contrasena de stdin."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "sudo").write_text(
        '#!/bin/sh\nread -r pw; shift 3; [ "$pw" = clave-de-prueba ] && "$@"\n'
    )
    (fake / "sudo").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    work = tmp_path / "trabajo"
    (work / "sub").mkdir(parents=True)
    a, b, pair_port = _paired(qt_application, loop, tmp_path)

    def run(command):
        b.console.run(command)
        _wait_until(qt_application, lambda: not b.view["running"])

    run(f"cd {work}")
    assert b.view["prompt"] == str(work)
    run("cd sub && pwd")
    assert b.view["prompt"] == str(work / "sub")
    assert f"{work} $ cd sub && pwd\n{work / 'sub'}\n" in b.text
    assert "MOLINK" not in b.text and "\x1e" not in b.text

    b.console.run("sudo echo como-root")
    assert b.view["asking"] and not b.view["running"]
    b.console.cancel()
    assert not b.view["asking"] and b.view["outcome"].text.startswith("No se corrió")
    b.console.run("sudo echo como-root")
    b.console.give_password("clave-de-prueba")
    _wait_until(qt_application, lambda: not b.view["running"])
    assert b.text.endswith("$ sudo echo como-root\ncomo-root\n")
    assert b.view["outcome"].text.startswith("Terminó con código 0")
    assert "clave-de-prueba" not in b.text and "clave-de-prueba" not in repr(b.views)

    cleared: list[bool] = []
    b.console.output_cleared.connect(lambda: cleared.append(True))
    b.console.run("clear")
    assert cleared == [True] and not b.view["running"] and b.text.endswith("como-root\n")

    assert b.console.history_older("") == "clear"
    assert b.console.history_older("") == "sudo echo como-root"
    assert b.console.history_older("") == "cd sub && pwd"
    _close(a, b, pair_port)
