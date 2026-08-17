"""Tests for execution/trailing_stop.py."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.execution.trailing_stop import (
    init_trailing_stop,
    should_trigger_exit,
    stop_price,
    update_peak,
)


def test_init_trailing_stop_sets_peak_to_entry() -> None:
    state = init_trailing_stop(Decimal("1.00"), trail_pct=Decimal("15"))
    assert state.peak_price == Decimal("1.00")


def test_init_trailing_stop_rejects_non_positive_entry() -> None:
    with pytest.raises(ValueError):
        init_trailing_stop(Decimal("0"), trail_pct=Decimal("15"))


def test_update_peak_raises_on_new_high() -> None:
    state = init_trailing_stop(Decimal("1.00"), trail_pct=Decimal("15"))
    state = update_peak(state, Decimal("2.00"))
    assert state.peak_price == Decimal("2.00")


def test_update_peak_ignores_lower_price() -> None:
    state = init_trailing_stop(Decimal("1.00"), trail_pct=Decimal("15"))
    state = update_peak(state, Decimal("2.00"))
    state = update_peak(state, Decimal("1.50"))
    assert state.peak_price == Decimal("2.00")  # peak never drops


def test_stop_price_computed_from_peak() -> None:
    state = init_trailing_stop(Decimal("1.00"), trail_pct=Decimal("20"))
    assert stop_price(state) == Decimal("0.80")


def test_should_trigger_exit_false_above_stop() -> None:
    state = init_trailing_stop(Decimal("1.00"), trail_pct=Decimal("20"))
    assert should_trigger_exit(state, Decimal("0.90")) is False


def test_should_trigger_exit_true_at_or_below_stop() -> None:
    state = init_trailing_stop(Decimal("1.00"), trail_pct=Decimal("20"))
    assert should_trigger_exit(state, Decimal("0.80")) is True
    assert should_trigger_exit(state, Decimal("0.70")) is True


def test_should_trigger_exit_uses_updated_peak() -> None:
    state = init_trailing_stop(Decimal("1.00"), trail_pct=Decimal("20"))
    state = update_peak(state, Decimal("2.00"))
    # 20% below the new peak of 2.00 is 1.60 — well above entry price
    assert should_trigger_exit(state, Decimal("1.70")) is False
    assert should_trigger_exit(state, Decimal("1.50")) is True
