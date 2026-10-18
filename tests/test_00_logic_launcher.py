from __future__ import annotations

from pathlib import Path

from logic._00_logic_launcher import desktop_entry, launcher_paths, quote_exec_arg


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


def test_entry_doubles_backslash_inside_quotes():
    entry = desktop_entry(Path("/a b/python"), Path("/p/main.py"), Path("/i.png"))
    assert _fields(entry)["Exec"] == '"/a b/python" /p/main.py'
    entry = desktop_entry(Path("/a\\b/python"), Path("/p/main.py"), Path("/i.png"))
    assert _fields(entry)["Exec"] == '"/a\\\\\\\\b/python" /p/main.py'


def test_launcher_id_matches_desktop_file_name():
    # Si no coinciden, el escritorio no asocia la ventana con el lanzador.
    from ui._00_ui_main import APP_NAME

    assert launcher_paths(Path("/d")).shortcut_file.stem == APP_NAME
