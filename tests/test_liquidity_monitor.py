"""Tests for execution/liquidity_monitor.py."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.execution.liquidity_monitor import monitor_post_entry_liquidity


async def test_monitor_rejects_non_positive_entry_liquidity() -> None:
    with pytest.raises(ValueError):
        await monitor_post_entry_liquidity("TOKEN", Decimal("0"), check_interval_seconds=1)


async def test_monitor_rejects_non_positive_interval() -> None:
    with pytest.raises(ValueError):
        await monitor_post_entry_liquidity(
            "TOKEN", Decimal("100000"), check_interval_seconds=0
        )


async def test_monitor_no_drop_does_not_trigger() -> None:
    callback = AsyncMock()
    with patch(
        "app.execution.liquidity_monitor.get_token_data", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = {"liquidity_usd": Decimal("100000")}
        result = await monitor_post_entry_liquidity(
            "TOKEN",
            entry_liquidity_usd=Decimal("100000"),
            on_emergency_exit=callback,
            check_interval_seconds=0.001,
            duration_seconds=10,  # bounded by max_checks, not real wall time
            max_checks=1,
        )

    assert result.triggered_emergency_exit is False
    assert result.checks_performed == 1
    callback.assert_not_called()


async def test_monitor_drop_triggers_callback() -> None:
    callback = AsyncMock()
    with patch(
        "app.execution.liquidity_monitor.get_token_data", new_callable=AsyncMock
    ) as mock_get:
        # 40% drop from entry — above the default 30% threshold
        mock_get.return_value = {"liquidity_usd": Decimal("60000")}
        result = await monitor_post_entry_liquidity(
            "TOKEN",
            entry_liquidity_usd=Decimal("100000"),
            on_emergency_exit=callback,
            check_interval_seconds=0.001,
            duration_seconds=10,
            max_checks=1,
        )

    assert result.triggered_emergency_exit is True
    callback.assert_awaited_once()
    args = callback.call_args.args
    assert args[0] == "TOKEN"
    assert args[1] == Decimal("100000")
    assert args[2] == Decimal("60000")


async def test_monitor_skips_interval_on_fetch_failure() -> None:
    callback = AsyncMock()
    with patch(
        "app.execution.liquidity_monitor.get_token_data", new_callable=AsyncMock
    ) as mock_get:
        mock_get.return_value = None
        result = await monitor_post_entry_liquidity(
            "TOKEN",
            entry_liquidity_usd=Decimal("100000"),
            on_emergency_exit=callback,
            check_interval_seconds=0.001,
            duration_seconds=10,
            max_checks=1,
        )

    assert result.triggered_emergency_exit is False
    assert result.checks_performed == 1
    callback.assert_not_called()


async def test_monitor_tracks_lowest_observed_liquidity() -> None:
    responses = [
        {"liquidity_usd": Decimal("90000")},
        {"liquidity_usd": Decimal("70000")},
        {"liquidity_usd": Decimal("85000")},
    ]
    with patch(
        "app.execution.liquidity_monitor.get_token_data", new_callable=AsyncMock
    ) as mock_get:
        mock_get.side_effect = responses
        result = await monitor_post_entry_liquidity(
            "TOKEN",
            entry_liquidity_usd=Decimal("100000"),
            check_interval_seconds=0.001,
            duration_seconds=10,
            drop_threshold_pct=Decimal("50"),  # avoid triggering, just track the low
            max_checks=3,
        )

    assert result.lowest_observed_liquidity_usd == Decimal("70000")
    assert result.checks_performed == 3


async def test_monitor_stops_at_duration_even_without_max_checks() -> None:
    """max_checks is a test convenience; duration_seconds is still the
    real production boundary and should stop the loop on its own."""
    call_count = {"n": 0}

    async def fake_get_token_data(token_mint: str):
        call_count["n"] += 1
        return {"liquidity_usd": Decimal("100000")}

    with patch(
        "app.execution.liquidity_monitor.get_token_data", new=fake_get_token_data
    ):
        result = await monitor_post_entry_liquidity(
            "TOKEN",
            entry_liquidity_usd=Decimal("100000"),
            check_interval_seconds=0.01,
            duration_seconds=0.02,  # elapsed hits exactly 0.02 on the 2nd check, loop stops
        )

    assert result.checks_performed == 2
    assert call_count["n"] == 2
