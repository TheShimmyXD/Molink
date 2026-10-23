"""Pruebas del sistema de cada equipo y de las ordenes de Windows."""

from __future__ import annotations

from logic._00_logic_platform import (
    OS_LINUX,
    OS_WINDOWS,
    is_windows,
    local_os,
    peer_os,
    powershell_file_args,
    powershell_script,
    sftp_local_path,
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


def test_powershell_script_deletes_itself_and_ends_like_sh():
    script = powershell_script('Write-Output "año"; cmd /c exit 3')
    lines = script.splitlines()
    assert lines[0].startswith("Remove-Item -LiteralPath $PSCommandPath")
    assert "UTF8" in lines[2]
    assert 'Write-Output "año"; cmd /c exit 3' in lines
    assert lines[-2].startswith("if (-not $?)") and lines[-1] == "exit 0"


def test_powershell_file_args():
    args = powershell_file_args("C:/tmp/molink-1.ps1")
    assert args[0] == "powershell.exe"
    assert "-NonInteractive" in args and "-NoProfile" in args
    assert args[-2:] == ["-File", "C:/tmp/molink-1.ps1"]
    assert args[args.index("-ExecutionPolicy") + 1] == "Bypass"


def test_taskkill_args_kill_the_tree():
    assert taskkill_args(1234) == ["taskkill.exe", "/T", "/F", "/PID", "1234"]


def test_sftp_local_path_turns_server_paths_into_windows_paths():
    path = "/C:/Users/ana/Descargas/Molink/a b.txt.part"
    assert sftp_local_path(path, "win32") == "C:\\Users\\ana\\Descargas\\Molink\\a b.txt.part"
    assert sftp_local_path(path, "linux") == path
    assert sftp_local_path("/home/ana/a.txt", "linux") == "/home/ana/a.txt"
