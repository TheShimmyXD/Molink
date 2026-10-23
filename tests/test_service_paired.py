"""Lista de emparejados: permisos, reemplazo, borrado y entradas danadas."""

from __future__ import annotations

import json

import asyncssh
import pytest

from services.service_identity import load_or_create_identity
from services.service_paired import (
    PAIRED_JSON_NAME,
    PeerRecord,
    add_paired,
    authorized_user_keys,
    load_paired,
    remove_paired,
)


def _pub(key: asyncssh.SSHKey) -> str:
    return key.export_public_key().decode()


def peer_of(tmp_path, name: str) -> PeerRecord:
    identity = load_or_create_identity(tmp_path / ("id-" + name))
    return PeerRecord.build(name, _pub(identity.user_key), _pub(identity.host_key))


def test_empty_when_missing(tmp_path):
    assert load_paired(tmp_path / "data") == []


@pytest.mark.linux_only
def test_added_peer_is_saved_private(tmp_path):
    data = tmp_path / "data"
    peer = peer_of(tmp_path, "sobremesa")
    add_paired(data, peer)
    assert (data / PAIRED_JSON_NAME).stat().st_mode & 0o777 == 0o600
    (loaded,) = load_paired(data)
    assert (loaded.name, loaded.user_key, loaded.host_key) == (
        peer.name,
        peer.user_key,
        peer.host_key,
    )
    assert loaded.paired_at


def test_same_name_or_host_key_replaces(tmp_path):
    data = tmp_path / "data"
    first = peer_of(tmp_path, "sobremesa")
    add_paired(data, first)
    renamed = PeerRecord.build("sobremesa2", first.user_key, first.host_key)
    add_paired(data, renamed)
    assert [p.name for p in load_paired(data)] == ["sobremesa2"]
    new_keys = peer_of(tmp_path, "otra")
    add_paired(data, PeerRecord.build("sobremesa2", new_keys.user_key, new_keys.host_key))
    (only,) = load_paired(data)
    assert only.host_key == new_keys.host_key


def test_remove(tmp_path):
    data = tmp_path / "data"
    add_paired(data, peer_of(tmp_path, "sobremesa"))
    assert remove_paired(data, "sobremesa") is True
    assert remove_paired(data, "sobremesa") is False
    assert authorized_user_keys(data) == []


def test_damaged_entry_is_skipped(tmp_path):
    data = tmp_path / "data"
    good = peer_of(tmp_path, "sobremesa")
    add_paired(data, good)
    raw = json.loads((data / PAIRED_JSON_NAME).read_text())
    raw["peers"].append({"name": "malo", "user_key": "ssh-ed25519 AAAA", "host_key": "x"})
    (data / PAIRED_JSON_NAME).write_text(json.dumps(raw))
    assert [p.name for p in load_paired(data)] == ["sobremesa"]


def test_unreadable_file_counts_as_empty(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / PAIRED_JSON_NAME).write_text("{roto")
    assert load_paired(data) == []


def test_only_ed25519_keys_are_accepted(tmp_path):
    good = peer_of(tmp_path, "sobremesa")
    ecdsa = _pub(asyncssh.generate_private_key("ecdsa-sha2-nistp256"))
    with pytest.raises(ValueError):
        PeerRecord.build("sobremesa", ecdsa, good.host_key)


def test_user_and_host_key_must_differ(tmp_path):
    good = peer_of(tmp_path, "sobremesa")
    with pytest.raises(ValueError):
        PeerRecord.build("sobremesa", good.user_key, good.user_key)


def test_comment_is_dropped(tmp_path):
    good = peer_of(tmp_path, "sobremesa")
    record = PeerRecord.build("sobremesa", good.user_key + " ana@laptop", good.host_key)
    assert record.user_key == good.user_key
    assert record.user_fingerprint().startswith("SHA256:")
