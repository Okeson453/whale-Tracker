"""Tests for state/circuit_breaker.py."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.state.circuit_breaker import (
    check_daily_loss,
    check_max_trades,
    get_daily_state,
    is_halted,
    record_trade,
    reset_breaker,
    trip_breaker,
)
from app.state.models import DailyState


async def test_get_daily_state_creates_row(session) -> None:
    state = await get_daily_state(session)
    assert state is not None
    assert state.date is not None
    assert state.halted is False
    assert state.trades_count == 0


async def test_is_halted_false_by_default(session) -> None:
    assert await is_halted(session) is False


async def test_trip_breaker(session) -> None:
    await trip_breaker(session, "test_reason")
    assert await is_halted(session) is True

    result = await session.execute(select(DailyState))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].halted is True


async def test_reset_breaker(session) -> None:
    await trip_breaker(session, "test")
    assert await is_halted(session) is True
    await reset_breaker(session)
    assert await is_halted(session) is False


async def test_record_trade_increments(session) -> None:
    await record_trade(session)
    await record_trade(session)
    state = await get_daily_state(session)
    assert state.trades_count == 2


async def test_check_max_trades_within_limit(session) -> None:
    assert await check_max_trades(session) is True


async def test_check_max_trades_at_limit(session) -> None:
    # Default max_trades_per_day from settings.yaml is 5
    for _ in range(5):
        await record_trade(session)
    assert await check_max_trades(session) is False


async def test_check_daily_loss_seeds_starting_balance_first_call(session) -> None:
    with patch(
        "app.state.circuit_breaker.get_wallet_usd_value", new_callable=AsyncMock
    ) as m_wallet:
        m_wallet.return_value = Decimal("1000")
        assert await check_daily_loss(session) is True

    state = await get_daily_state(session)
    assert state.starting_balance == Decimal("1000")
    assert state.halted is False


async def test_check_daily_loss_trips_breaker_past_threshold(session) -> None:
    # Default daily_loss_halt_pct from settings.yaml is 20
    with patch(
        "app.state.circuit_breaker.get_wallet_usd_value", new_callable=AsyncMock
    ) as m_wallet:
        m_wallet.return_value = Decimal("1000")
        await check_daily_loss(session)  # seeds starting_balance at 1000

        m_wallet.return_value = Decimal("750")  # 25% down
        result = await check_daily_loss(session)

    assert result is False
    assert await is_halted(session) is True


async def test_check_daily_loss_within_threshold_does_not_halt(session) -> None:
    with patch(
        "app.state.circuit_breaker.get_wallet_usd_value", new_callable=AsyncMock
    ) as m_wallet:
        m_wallet.return_value = Decimal("1000")
        await check_daily_loss(session)  # seeds starting_balance at 1000

        m_wallet.return_value = Decimal("900")  # 10% down, under the 20% threshold
        result = await check_daily_loss(session)

    assert result is True
    assert await is_halted(session) is False


async def test_check_daily_loss_fails_open_when_price_unavailable(session) -> None:
    with patch(
        "app.state.circuit_breaker.get_wallet_usd_value", new_callable=AsyncMock
    ) as m_wallet:
        m_wallet.return_value = None
        result = await check_daily_loss(session)

    assert result is True
    assert await is_halted(session) is False
