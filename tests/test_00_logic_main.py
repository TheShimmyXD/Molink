from __future__ import annotations

import logic._00_logic_main as main_logic
from logic._00_logic_main import MainLogic, MainState, NavigationItem


def _with_items(monkeypatch, *items: NavigationItem) -> None:
    monkeypatch.setattr(main_logic, "NAVIGATION_ITEMS", items)


def test_starts_ready(monkeypatch):
    _with_items(monkeypatch, NavigationItem("alpha", "Alfa", "Módulo alfa"))
    logic = MainLogic()
    assert logic.state == MainState.NAVIGATION_READY
    assert logic.get_default_module_id() == "alpha"


def test_open_existing_module(monkeypatch):
    _with_items(monkeypatch, NavigationItem("alpha", "Alfa", "Módulo alfa"))
    payload = MainLogic().open_module("alpha")
    assert payload["ok"] is True
    assert payload["state"] == MainState.MODULE_ACTIVE.value


def test_open_unknown_module(monkeypatch):
    _with_items(monkeypatch, NavigationItem("alpha", "Alfa", "Módulo alfa"))
    payload = MainLogic().open_module("missing")
    assert payload["ok"] is False
    assert payload["state"] == MainState.MODULE_NOT_FOUND.value


def test_admin_only_hidden_for_operator(monkeypatch):
    _with_items(
        monkeypatch,
        NavigationItem("alpha", "Alfa", "Módulo alfa"),
        NavigationItem("credentials", "Credenciales", "Administración", admin_only=True),
    )
    ids = [item.module_id for item in MainLogic(is_admin=False).get_navigation_items()]
    assert ids == ["alpha"]
    ids = [item.module_id for item in MainLogic(is_admin=True).get_navigation_items()]
    assert ids == ["alpha", "credentials"]
