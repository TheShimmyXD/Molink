from __future__ import annotations

import json

from config import AppConfig, as_float, as_int, as_str, load_app_config, save_app_config


def test_coercion_falls_back_to_default():
    assert as_int("abc", 5) == 5
    assert as_int(-3, 5) == 5
    assert as_int("7", 5) == 7
    assert as_float(None, 1.5) == 1.5
    assert as_str("   ", "x") == "x"


def test_missing_file_gives_defaults(tmp_path):
    config = load_app_config(tmp_path / "missing.json")
    assert config == AppConfig()


def test_corrupt_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_app_config(path) == AppConfig()


def test_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    original = AppConfig(debug=True, theme="dark")
    assert save_app_config(original, path)
    assert load_app_config(path) == original
    assert json.loads(path.read_text(encoding="utf-8"))["theme"] == "dark"


def test_unknown_theme_falls_back_to_light(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"theme": "neon"}', encoding="utf-8")
    assert load_app_config(path).theme == "light"
