"""Pantalla de emparejar con el coordinador de vista previa: sin red ni datos reales."""

from __future__ import annotations

import pytest

from modules.mod_02_pair._02_coordinator_preview import SAMPLES, PreviewPairCoordinator
from modules.mod_02_pair.ui._02_ui_pair import PairWidget


def _screen(sample: str) -> tuple[PairWidget, PreviewPairCoordinator]:
    coordinator = PreviewPairCoordinator(sample)
    return PairWidget(coordinator), coordinator


def test_opening_the_screen_starts_the_link(qt_application):
    _, coordinator = _screen("starting")
    assert coordinator.calls == [("start",)]


def test_found_peers_new_and_paired(qt_application):
    screen, coordinator = _screen("found")
    new, paired = screen._rows["sobremesa"], screen._rows["taller"]
    assert not new.code.isHidden() and new.join_button.isEnabled()
    assert new.forget_button.isHidden() and not paired.forget_button.isHidden()
    assert paired.code.isHidden() and paired.address.text() == "192.0.2.30"
    new.code.setText("000 000")
    new.join_button.click()
    paired.forget_button.click()
    screen.show_button.click()
    assert coordinator.calls[1:] == [
        ("join", "sobremesa", 7),
        ("forget", "taller"),
        ("open_window",),
    ]


def test_joining_disables_the_row_and_error_shows_under_it(qt_application):
    screen, _ = _screen("joining")
    row = screen._rows["sobremesa"]
    assert not row.join_button.isEnabled() and row.join_button.text() == "Emparejando..."
    screen, _ = _screen("join_error")
    row = screen._rows["sobremesa"]
    assert row.join_button.isEnabled() and "no coincide" in row.error.text()
    assert not row.error.isHidden()


def test_window_shows_code_and_countdown(qt_application):
    screen, coordinator = _screen("window")
    assert screen.code_label.text() == "000 000" and screen.countdown.text() == "vence en 1:52"
    assert screen.show_button.isHidden() and not screen.close_button.isHidden()
    screen.close_button.click()
    assert coordinator.calls[-1] == ("close_window",)
    screen, _ = _screen("found")
    assert screen.code_label.isHidden() and not screen.show_button.isHidden()


def test_error_explains_and_disables_actions(qt_application):
    # Reintentar lo lleva la linea del pie de la ventana.
    screen, coordinator = _screen("error")
    assert "ocupado" in screen.status_text.text() and "Ciérralo" in screen.status_text.text()
    assert not screen.show_button.isEnabled()
    assert coordinator.calls == [("start",)]


def test_rows_keep_typed_code_when_the_view_repeats(qt_application):
    screen, coordinator = _screen("found")
    row = screen._rows["sobremesa"]
    row.code.setText("123")
    screen.render(coordinator.view())
    assert screen._rows["sobremesa"] is row and row.code.text() == "123"


@pytest.mark.parametrize("sample", sorted(SAMPLES))
def test_every_sample_renders_and_closes(qt_application, sample):
    screen, coordinator = _screen(sample)
    screen.close()
    assert coordinator.calls[-1] == ("close",)
