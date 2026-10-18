"""Carpeta de trabajo, historial y sudo de la consola, sin red."""

from __future__ import annotations

import subprocess

import pytest

from modules.mod_03_console.logic._03_logic_shell import (
    MARK,
    STDERR,
    CommandHistory,
    Place,
    ShellMarkFilter,
    needs_password,
    short_path,
    wrap_command,
)

STDOUT = "stdout"


def _run(script: str, stdin: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.run(["sh", "-c", script], input=stdin, capture_output=True, timeout=10)


def _filtered(stderr: bytes, chunk: int) -> tuple[bytes, Place | None]:
    marks = ShellMarkFilter()
    shown = b"".join(
        marks.feed(STDERR, stderr[i : i + chunk]) for i in range(0, len(stderr), chunk)
    )
    rest, place = marks.finish()
    return shown + rest, place


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("sudo apt update", True),
        ("cd /tmp && sudo ls", True),
        ("echo hola; sudo -k", True),
        ("(sudo true)", True),
        ("sudoku", False),
        ("echo pseudo sudoers", False),
        ("ls", False),
    ],
)
def test_needs_password(command, expected):
    assert needs_password(command) is expected


def test_short_path():
    assert short_path("", "/home/ana") == "~"
    assert short_path("/home/ana", "/home/ana") == "~"
    assert short_path("/home/ana/Descargas", "/home/ana/") == "~/Descargas"
    assert short_path("/home/anabel", "/home/ana") == "/home/anabel"
    assert short_path("/tmp", "") == "/tmp"


@pytest.mark.parametrize("chunk", [1, 3, 4096])
def test_wrapped_command_keeps_status_and_reports_folder(tmp_path, chunk):
    folder = tmp_path / "con espacio 'y comilla'"
    folder.mkdir()
    (folder / "sub").mkdir()
    done = _run(wrap_command("cd sub; echo error >&2; exit 3", str(folder), with_sudo=False))
    assert done.returncode == 3
    assert done.stdout == b""
    shown, place = _filtered(done.stderr, chunk)
    assert shown == b"error\n"
    assert place is not None and place.cwd == str(folder / "sub") and place.home


def test_empty_folder_starts_at_home_and_missing_folder_falls_back(tmp_path):
    first = _run(wrap_command("pwd", "", with_sudo=False))
    _, place = _filtered(first.stderr, 4096)
    assert first.stdout.decode().strip() == place.home == place.cwd

    gone = _run(wrap_command("true", str(tmp_path / "no-existe"), with_sudo=False))
    _, place = _filtered(gone.stderr, 4096)
    assert gone.returncode == 0 and place.cwd == place.home


def test_syntax_error_still_reports_folder(tmp_path):
    done = _run(wrap_command("echo (", str(tmp_path), with_sudo=False))
    shown, place = _filtered(done.stderr, 4096)
    assert done.returncode != 0 and b"MOLINK" not in shown and place.cwd == str(tmp_path)


def test_sudo_reads_password_from_stdin_without_prompt(tmp_path, monkeypatch):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "sudo").write_text(
        '#!/bin/sh\n[ "$1" = -S ] && [ "$2" = -p ] && [ "$3" = "" ] || exit 9\n'
        'read -r pw; shift 3; [ "$pw" = clave-de-prueba ] && "$@"\n'
    )
    (fake / "sudo").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:/usr/bin:/bin")
    script = wrap_command("sudo echo como-root", str(tmp_path), with_sudo=True)
    assert "clave-de-prueba" not in script
    done = _run(script, stdin=b"clave-de-prueba\n")
    assert done.returncode == 0 and done.stdout == b"como-root\n"
    wrong = _run(script, stdin=b"otra\n")
    assert wrong.returncode != 0 and wrong.stdout == b""


def test_filter_leaves_stdout_and_unfinished_mark_alone():
    marks = ShellMarkFilter()
    assert marks.feed(STDOUT, MARK) == MARK
    assert marks.feed(STDERR, b"hola\x1eMOL") == b"hola"
    assert marks.finish() == (b"\x1eMOL", None)
    assert marks.feed(STDERR, MARK + b"/tmp") == b""
    assert marks.finish() == (MARK + b"/tmp", None)


def test_history_walks_like_a_shell():
    history = CommandHistory(size=3)
    assert history.older("algo") == "algo"
    for command in ("ls", "ls", " pwd ", "", "df", "hostname"):
        history.add(command)
    assert history.items == ("pwd", "df", "hostname")
    assert history.older("a medias") == "hostname"
    assert history.older("") == "df"
    assert history.older("") == "pwd"
    assert history.older("") == "pwd"
    assert history.newer() == "df"
    assert history.newer() == "hostname"
    assert history.newer() == "a medias"
    assert history.newer() == "a medias"
