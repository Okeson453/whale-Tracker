"""Tests for execution/dynamic_sizing.py."""

from __future__ import annotations

from decimal import Decimal

from app.analytics.analytics_models import WalletScorecardDataclass
from app.execution.dynamic_sizing import calculate_position_size


def _scorecard(total: int, passed: int) -> WalletScorecardDataclass:
    return WalletScorecardDataclass(
        wallet_id="w1",
        wallet_address="addr1",
        total_alerts=total,
        passed_alerts=passed,
    )


def test_no_scorecard_sizes_at_minimum() -> None:
    size = calculate_position_size(None)
    assert size == Decimal("50")


def test_zero_alerts_sizes_at_minimum() -> None:
    size = calculate_position_size(_scorecard(0, 0))
    assert size == Decimal("50")


def test_pass_rate_at_ceiling_sizes_at_max() -> None:
    sc = _scorecard(10, 8)  # 80% pass rate == ceiling
    size = calculate_position_size(sc)
    assert size == Decimal("500")


def test_pass_rate_above_ceiling_still_caps_at_max() -> None:
    sc = _scorecard(10, 10)  # 100% pass rate
    size = calculate_position_size(sc)
    assert size == Decimal("500")


def test_pass_rate_midway_interpolates() -> None:
    sc = _scorecard(10, 4)  # 40% pass rate, half of 80% ceiling
    size = calculate_position_size(sc)
    assert Decimal("270") <= size <= Decimal("280")  # ~$275 expected


def test_zero_pass_rate_sizes_at_minimum() -> None:
    sc = _scorecard(10, 0)
    size = calculate_position_size(sc)
    assert size == Decimal("50")
