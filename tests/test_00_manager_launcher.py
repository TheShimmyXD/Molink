from __future__ import annotations

import base64
import subprocess

import pytest
from PySide6.QtGui import QColor, QPixmap

from logic._00_logic_launcher import shortcut_script
from managers import launcher


@pytest.fixture()
def icon(qt_application):
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#336699"))
    return pixmap


@pytest.fixture()
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "is_windows", lambda: True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    return calls


def test_windows_writes_ico_and_runs_encoded_script(icon, windows, tmp_path):
    paths = launcher.install_launcher(icon)
    assert paths.icon_file == tmp_path / "Local" / "Molink" / "Molink.ico"
    assert paths.icon_file.read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert paths.shortcut_file.parent.is_dir()
    (args,) = windows
    assert args[0] == "powershell.exe" and args[-2] == "-EncodedCommand"
    script = base64.b64decode(args[-1]).decode("utf-16-le")
    pythonw = launcher.Path(launcher.sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = launcher.Path(launcher.sys.executable)
    assert script == shortcut_script(
        paths.shortcut_file, pythonw, launcher.ROOT / "main.py", paths.icon_file
    )


def test_windows_powershell_failure_is_oserror(icon, windows, monkeypatch):
    monkeypatch.setattr(
        launcher.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 1)
    )
    with pytest.raises(OSError, match="codigo 1"):
        launcher.install_launcher(icon)


@pytest.mark.linux_only
def test_linux_writes_png_and_desktop(icon, tmp_path):
    paths = launcher.install_launcher(icon, data_home=tmp_path)
    assert paths.icon_file.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert paths.shortcut_file.read_text(encoding="utf-8").startswith("[Desktop Entry]\n")
