from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from logic._00_logic_launcher import (
    desktop_entry,
    launcher_paths,
    quote_exec_arg,
    quote_powershell,
    shortcut_script,
    windows_launcher_paths,
)


def _fields(entry: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in entry.splitlines()[1:])


def test_paths_inside_data_home(tmp_path):
    paths = launcher_paths(tmp_path)
    assert paths.shortcut_file == tmp_path / "applications" / "Molink.desktop"
    assert paths.icon_file == tmp_path / "icons" / "hicolor" / "256x256" / "apps" / "Molink.png"


def test_plain_arg_without_quotes():
    assert quote_exec_arg("/opt/app/main.py") == "/opt/app/main.py"


def test_arg_with_space_and_dollar_is_quoted():
    assert quote_exec_arg("/mis cosas/$x.py") == '"/mis cosas/\\$x.py"'


@pytest.mark.linux_only
def test_entry_fields():
    entry = desktop_entry(Path("/p/.venv/bin/python"), Path("/p/main.py"), Path("/i/Molink.png"))
    assert entry.startswith("[Desktop Entry]\n")
    fields = _fields(entry)
    assert fields["Type"] == "Application"
    assert fields["Exec"] == "/p/.venv/bin/python /p/main.py"
    assert fields["Path"] == "/p"
    assert fields["Icon"] == "/i/Molink.png"
    assert fields["Terminal"] == "false"
    assert fields["StartupWMClass"] == "Molink"


@pytest.mark.linux_only
def test_entry_doubles_backslash_inside_quotes():
    entry = desktop_entry(Path("/a b/python"), Path("/p/main.py"), Path("/i.png"))
    assert _fields(entry)["Exec"] == '"/a b/python" /p/main.py'
    entry = desktop_entry(Path("/a\\b/python"), Path("/p/main.py"), Path("/i.png"))
    assert _fields(entry)["Exec"] == '"/a\\\\\\\\b/python" /p/main.py'


def test_launcher_id_matches_desktop_file_name():
    # Si no coinciden, el escritorio no asocia la ventana con el lanzador.
    from ui._00_ui_main import APP_NAME

    assert launcher_paths(Path("/d")).shortcut_file.stem == APP_NAME


def test_windows_paths_in_start_menu_and_local_appdata():
    paths = windows_launcher_paths(
        PureWindowsPath(r"C:\Users\ana\AppData\Roaming"),
        PureWindowsPath(r"C:\Users\ana\AppData\Local"),
    )
    assert str(paths.shortcut_file) == (
        r"C:\Users\ana\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Molink.lnk"
    )
    assert str(paths.icon_file) == r"C:\Users\ana\AppData\Local\Molink\Molink.ico"


def test_powershell_quote_doubles_single_quote():
    assert quote_powershell("C:\\O'Brien\\año $x") == "'C:\\O''Brien\\año $x'"


def test_shortcut_script_fields():
    root = PureWindowsPath(r"C:\Users\O'Brien\Molink")
    script = shortcut_script(
        PureWindowsPath(r"C:\S\Molink.lnk"),
        root / ".venv" / "Scripts" / "pythonw.exe",
        root / "main.py",
        PureWindowsPath(r"C:\L\Molink\Molink.ico"),
    )
    lines = script.splitlines()
    assert lines[0] == "$ErrorActionPreference = 'Stop'"
    assert "$link = $shell.CreateShortcut('C:\\S\\Molink.lnk')" in lines
    assert "$link.TargetPath = 'C:\\Users\\O''Brien\\Molink\\.venv\\Scripts\\pythonw.exe'" in lines
    assert "$link.Arguments = '\"C:\\Users\\O''Brien\\Molink\\main.py\"'" in lines
    assert "$link.WorkingDirectory = 'C:\\Users\\O''Brien\\Molink'" in lines
    assert "$link.IconLocation = 'C:\\L\\Molink\\Molink.ico,0'" in lines
    assert lines[-1] == "$link.Save()"
