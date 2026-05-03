"""Tests for SpanshTools.widgets validators and clamp logic."""

import pytest

from SpanshTools.widgets import (
    validate_integer_input,
    validate_decimal_input,
    validate_spinbox_input,
    clamp_spinbox_input,
)
from conftest import DummyEntry


def test_validate_integer_accepts_and_rejects():
    assert validate_integer_input("123") is True
    assert validate_integer_input("") is True
    assert validate_integer_input("abc") is False
    assert validate_integer_input("12a3") is False
    assert validate_integer_input("1.5") is False
    assert validate_integer_input("-5") is False
    assert validate_integer_input("-5", signed=True) is True
    assert validate_integer_input("-", signed=True) is True


def test_validate_decimal_accepts_and_rejects():
    assert validate_decimal_input("3.14") is True
    assert validate_decimal_input("42") is True
    assert validate_decimal_input("") is True
    assert validate_decimal_input(".") is True
    assert validate_decimal_input("3.") is True
    assert validate_decimal_input("1.2.3") is False
    assert validate_decimal_input("abc") is False
    assert validate_decimal_input("-3.14") is False
    assert validate_decimal_input("-3.14", signed=True) is True
    assert validate_decimal_input("3.141", maximum_decimals=2) is False
    assert validate_decimal_input("3.14", maximum_decimals=2) is True


def test_validate_spinbox_integer_and_float_modes():
    assert validate_spinbox_input("42") is True
    assert validate_spinbox_input("3.14") is False
    assert validate_spinbox_input("3.14", allow_float=True) is True
    assert validate_spinbox_input("9999", max_digits=3) is False
    assert validate_spinbox_input("999", max_digits=3) is True


def test_clamp_above_maximum():
    entry = DummyEntry("150", 0, 100)
    values = []
    result = clamp_spinbox_input(entry, set_entry_value=lambda w, v: values.append(v))
    assert result == 100.0
    assert values == [100.0]


def test_clamp_integer_mode_truncates():
    entry = DummyEntry("7.9", 0, 100)
    result = clamp_spinbox_input(entry, integer=True, set_entry_value=lambda w, v: None)
    assert result == 7
    assert isinstance(result, int)


def test_clamp_tolerates_intermediate_values():
    for value in ("", "-", "."):
        entry = DummyEntry(value, 0, 100)
        result = clamp_spinbox_input(entry, tolerate_intermediate=True, set_entry_value=lambda w, v: None)
        assert result is None


def test_clamp_raises_on_invalid_when_not_tolerated():
    entry = DummyEntry("abc", 0, 100)
    with pytest.raises(ValueError, match="Invalid number"):
        clamp_spinbox_input(entry, set_entry_value=lambda w, v: None)


def test_clamp_return_none_on_invalid():
    entry = DummyEntry("abc", 0, 100)
    result = clamp_spinbox_input(entry, return_none_on_invalid=True, set_entry_value=lambda w, v: None)
    assert result is None
