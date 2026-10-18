"""Eleccion de equipo comun a Consola, Archivos y Chat."""

from __future__ import annotations

from logic._00_logic_targets import TargetChoice, seconds_text


class _Busy(TargetChoice):
    def __init__(self) -> None:
        super().__init__()
        self.working = False

    @property
    def busy(self) -> bool:
        return self.working


def test_first_reachable_is_chosen_and_replaced_when_it_leaves():
    choice = TargetChoice()
    choice.set_targets([("sobremesa", "10.0.0.2"), ("taller", "10.0.0.3")])
    assert (choice.target, choice.address) == ("sobremesa", "10.0.0.2")
    assert choice.choose("taller") and not choice.choose("nadie")
    choice.set_targets([("sobremesa", "10.0.0.2")])
    assert choice.target == "sobremesa"
    choice.set_targets([])
    assert (choice.target, choice.address) == ("", "")


def test_busy_keeps_the_target_until_it_settles():
    choice = _Busy()
    choice.set_targets([("sobremesa", "10.0.0.2"), ("taller", "10.0.0.3")])
    choice.working = True
    assert not choice.choose("taller")
    choice.set_targets([("taller", "10.0.0.3")])
    assert choice.target == "sobremesa"
    choice.working = False
    choice._settle()
    assert choice.target == "taller"


def test_seconds_text_uses_comma_and_never_negative():
    assert (seconds_text(2.345), seconds_text(-1)) == ("2,3 s", "0,0 s")
