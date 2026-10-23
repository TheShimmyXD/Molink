"""Identidad del equipo: permisos 700/600, reutilizacion y nada en ~/.ssh."""

from __future__ import annotations

import json

import asyncssh
import pytest

from services import service_identity
from services.service_identity import (
    HOST_KEY_NAME,
    IDENTITY_JSON_NAME,
    USER_KEY_NAME,
    check_data_dir,
    check_device_name,
    default_data_dir,
    default_device_name,
    ensure_private_dir,
    load_or_create_identity,
    save_device_name,
)

PRIVATE_FILES = [
    USER_KEY_NAME,
    USER_KEY_NAME + ".pub",
    HOST_KEY_NAME,
    HOST_KEY_NAME + ".pub",
    IDENTITY_JSON_NAME,
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """HOME falso en tmp_path: la prueba no puede tocar el ~/.ssh real."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    monkeypatch.setenv("LOCALAPPDATA", str(fake / "AppData" / "Local"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return fake


def _mode(path):
    return path.stat().st_mode & 0o777


@pytest.mark.linux_only
def test_identity_is_created_with_private_permissions(home):
    identity = load_or_create_identity()
    data = home / ".local" / "share" / "molink"
    assert identity.data_dir == data.resolve()
    assert _mode(data) == 0o700
    assert sorted(p.name for p in data.iterdir()) == sorted(PRIVATE_FILES)
    for name in PRIVATE_FILES:
        assert _mode(data / name) == 0o600, name


def test_nothing_is_written_in_ssh_dir(home):
    load_or_create_identity()
    assert not (home / ".ssh").exists()


def test_keys_are_ed25519_and_distinct(home):
    identity = load_or_create_identity()
    assert identity.user_key.algorithm == b"ssh-ed25519"
    assert identity.host_key.algorithm == b"ssh-ed25519"
    assert identity.user_key.public_data != identity.host_key.public_data


def test_pub_file_matches_private_key(home):
    identity = load_or_create_identity()
    pub = asyncssh.read_public_key(str(identity.data_dir / (USER_KEY_NAME + ".pub")))
    assert pub.public_data == identity.user_key.public_data


def test_identity_is_reused(home):
    first = load_or_create_identity()
    second = load_or_create_identity()
    assert second.name == first.name
    assert second.user_key.public_data == first.user_key.public_data
    assert second.host_key.public_data == first.host_key.public_data


@pytest.mark.parametrize("inside", ["", "molink", "a/b"])
def test_ssh_dir_is_rejected(home, inside):
    with pytest.raises(ValueError):
        check_data_dir(home / ".ssh" / inside)


def test_ssh_dir_is_rejected_before_writing(home):
    with pytest.raises(ValueError):
        load_or_create_identity(home / ".ssh" / "molink")
    assert not (home / ".ssh").exists()


@pytest.mark.linux_only
def test_loose_permissions_are_tightened(home):
    data = home / "data"
    load_or_create_identity(data)
    data.chmod(0o755)
    (data / USER_KEY_NAME).chmod(0o644)
    (data / IDENTITY_JSON_NAME).chmod(0o644)
    load_or_create_identity(data)
    assert _mode(data) == 0o700
    assert _mode(data / USER_KEY_NAME) == 0o600
    assert _mode(data / IDENTITY_JSON_NAME) == 0o600


@pytest.mark.linux_only
def test_xdg_data_home_is_respected(home, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert default_data_dir() == tmp_path / "xdg" / "molink"


@pytest.mark.linux_only
def test_relative_xdg_data_home_is_ignored(home, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "relativa")
    assert default_data_dir() == home / ".local" / "share" / "molink"


@pytest.mark.parametrize("name", ["jack-laptop", "a", "Sobremesa2", "x" * 63])
def test_valid_device_names(name):
    assert check_device_name(name) == name


@pytest.mark.parametrize("name", ["", "-a", "a-", "con espacio", "a.b", "x" * 64, "año"])
def test_invalid_device_names(name):
    with pytest.raises(ValueError):
        check_device_name(name)


def test_default_name_is_a_dns_label(monkeypatch):
    monkeypatch.setattr(service_identity.socket, "gethostname", lambda: "Jack's PC.lan")
    assert default_device_name() == "Jack-s-PC"


def test_unusable_hostname_falls_back(monkeypatch):
    monkeypatch.setattr(service_identity.socket, "gethostname", lambda: "---")
    assert default_device_name() == "molink"


def test_saved_name_is_kept(home):
    data = home / "data"
    load_or_create_identity(data)
    save_device_name(data, "sobremesa")
    assert load_or_create_identity(data).name == "sobremesa"


def test_damaged_identity_json_is_rebuilt(home, monkeypatch):
    monkeypatch.setattr(service_identity.socket, "gethostname", lambda: "equipo")
    data = home / "data"
    load_or_create_identity(data)
    (data / IDENTITY_JSON_NAME).write_text("{no es json")
    assert load_or_create_identity(data).name == "equipo"
    assert json.loads((data / IDENTITY_JSON_NAME).read_text()) == {"name": "equipo"}


def test_windows_data_dir_and_no_chmod(monkeypatch, tmp_path):
    monkeypatch.setattr("services.service_identity.is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert default_data_dir() == tmp_path / "local" / "Molink"
    data = tmp_path / "datos"
    data.mkdir(mode=0o755)
    before = _mode(data)
    ensure_private_dir(data)
    assert _mode(data) == before
