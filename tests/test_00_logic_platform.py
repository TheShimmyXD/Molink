"""Pruebas del sistema de cada equipo y de las ordenes de Windows."""

from __future__ import annotations

import base64

from logic._00_logic_platform import (
    OS_LINUX,
    OS_WINDOWS,
    is_windows,
    local_os,
    peer_os,
    powershell_args,
    taskkill_args,
)


def test_local_os():
    assert local_os("win32") == OS_WINDOWS
    assert local_os("linux") == OS_LINUX
    assert is_windows("win32") and not is_windows("linux")


def test_peer_os_without_key_is_linux():
    assert peer_os(None) == OS_LINUX
    assert peer_os(b"windows") == OS_WINDOWS
    assert peer_os("windows") == OS_WINDOWS
    assert peer_os("macos") == OS_LINUX
    assert peer_os(b"\xff") == OS_LINUX


def test_powershell_args_encode_the_command():
    command = 'Write-Output "año y $HOME"; dir'
    args = powershell_args(command)
    assert args[0] == "powershell.exe"
    assert "-NonInteractive" in args and "-NoProfile" in args
    assert args[-2] == "-EncodedCommand"
    script = base64.b64decode(args[-1]).decode("utf-16-le")
    assert script.endswith("\n" + command)
    assert "UTF8" in script.splitlines()[0]


def test_taskkill_args_kill_the_tree():
    assert taskkill_args(1234) == ["taskkill.exe", "/T", "/F", "/PID", "1234"]
