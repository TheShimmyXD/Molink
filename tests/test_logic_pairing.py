"""Ventana de emparejamiento: plazo, intentos y codigo."""

from __future__ import annotations

import pytest

from logic._00_logic_pairing import (
    MAX_ATTEMPTS,
    WINDOW_SECONDS,
    PairingState,
    PairingWindow,
    new_code,
    normalize_code,
)


def test_code_has_six_digits_with_leading_zeros():
    assert new_code(lambda _n: 42) == "000042"
    assert new_code(lambda n: n - 1) == "999999"


def test_random_code_is_valid():
    for _ in range(50):
        code = new_code()
        assert normalize_code(code) == code


@pytest.mark.parametrize("text", ["123456", " 123 456 ", "123-456"])
def test_code_is_normalized(text):
    assert normalize_code(text) == "123456"


@pytest.mark.parametrize(
    "text", ["", "12345", "1234567", "12a456", "\u0661\u0662\u0663\u0664\u0665\u0666"]
)
def test_bad_code_is_rejected(text):
    with pytest.raises(ValueError):
        normalize_code(text)


def test_window_starts_open():
    window = PairingWindow(now=0.0)
    assert window.state(0.0) is PairingState.OPEN
    assert window.remaining(30.0) == WINDOW_SECONDS - 30.0


def test_window_expires_after_two_minutes():
    window = PairingWindow(now=0.0)
    assert window.state(WINDOW_SECONDS - 0.001) is PairingState.OPEN
    assert window.state(WINDOW_SECONDS) is PairingState.EXPIRED
    assert window.start_attempt(WINDOW_SECONDS) is PairingState.EXPIRED
    assert window.attempts_left == MAX_ATTEMPTS


def test_attempts_are_counted_when_they_start():
    window = PairingWindow(now=0.0)
    for _ in range(MAX_ATTEMPTS):
        assert window.start_attempt(1.0) is PairingState.OPEN
    assert window.state(1.0) is PairingState.LOCKED
    assert window.start_attempt(1.0) is PairingState.LOCKED


def test_success_pairs_and_burns_the_code():
    window = PairingWindow(now=0.0)
    window.start_attempt(1.0)
    assert window.finish_attempt(2.0, success=True) is PairingState.PAIRED
    assert window.start_attempt(3.0) is PairingState.PAIRED


def test_success_after_deadline_does_not_pair():
    window = PairingWindow(now=0.0)
    window.start_attempt(WINDOW_SECONDS - 1)
    assert window.finish_attempt(WINDOW_SECONDS + 1, success=True) is PairingState.EXPIRED


def test_failure_keeps_window_open_while_attempts_remain():
    window = PairingWindow(now=0.0)
    window.start_attempt(1.0)
    assert window.finish_attempt(2.0, success=False) is PairingState.OPEN
    assert window.attempts_left == MAX_ATTEMPTS - 1


def test_close_cancels():
    window = PairingWindow(now=0.0)
    window.close()
    assert window.state(1.0) is PairingState.CLOSED
    assert window.remaining(1.0) == 0.0
