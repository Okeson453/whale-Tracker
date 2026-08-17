"""Circuit breaker — tracks daily PnL / trade count, enforces hard stops."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import yaml_settings
from app.execution.pricing import get_wallet_usd_value
from app.state.models import DailyState

logger = logging.getLogger(__name__)


def _today_str() -> str:
    return date.today().isoformat()


async def get_daily_state(session: AsyncSession) -> DailyState:
    """Fetch or create today's DailyState row.

    Deliberately does *not* fetch the trading wallet's balance here —
    this is called on essentially every request (``is_halted``,
    ``record_trade``, ``check_max_trades``), so adding a network round
    trip to all of them would slow down every trade decision and every
    test that touches the circuit breaker. ``starting_balance`` is seeded
    lazily, once, the first time ``check_daily_loss`` actually needs it.
    """
    today = _today_str()
    result = await session.execute(
        select(DailyState).where(DailyState.date == today)
    )
    state = result.scalar_one_or_none()
    if state is None:
        state = DailyState(date=today)
        session.add(state)
        await session.commit()
        await session.refresh(state)
    return state


async def is_halted(session: AsyncSession) -> bool:
    """Return True if the circuit breaker is currently tripped."""
    state = await get_daily_state(session)
    return state.halted


async def record_trade(session: AsyncSession) -> None:
    """Increment the daily trade counter."""
    state = await get_daily_state(session)
    state.trades_count += 1
    await session.commit()


async def check_max_trades(session: AsyncSession) -> bool:
    """Return True if today's trade count is within the allowed limit."""
    thresholds = yaml_settings.circuit_breaker
    max_trades = thresholds.get("max_trades_per_day")
    if max_trades is None:
        return True
    state = await get_daily_state(session)
    return state.trades_count < int(max_trades)


async def check_daily_loss(session: AsyncSession) -> bool:
    """Return True if today's drawdown is within the configured limit.

    Compares the trading wallet's current USD value against today's
    ``starting_balance``, seeding ``starting_balance`` from the live
    wallet value on the first call of the day (so a value we've never
    recorded doesn't read as a 100% loss). Trips (and persists) the halt
    when the loss exceeds ``circuit_breaker.daily_loss_halt_pct``.

    This is the actual capital-protection check that
    ``daily_loss_halt_pct`` promises — previously that setting was
    validated at startup but nothing ever compared live PnL against it,
    so the bot would keep trading through an unbounded daily loss.

    Fails open (returns True, does not halt, does not seed) when the
    current wallet value can't be fetched at all — an RPC/price outage
    shouldn't itself look like a loss — but logs a warning so the outage
    is visible.
    """
    thresholds = yaml_settings.circuit_breaker
    max_loss_pct = thresholds.get("daily_loss_halt_pct")
    if max_loss_pct is None:
        return True

    state = await get_daily_state(session)
    if state.halted:
        return False

    current_balance = await get_wallet_usd_value()
    if current_balance is None:
        logger.warning("Daily loss check skipped — current wallet value unavailable")
        return True

    if state.starting_balance is None or state.starting_balance <= 0:
        state.starting_balance = current_balance
        await session.commit()
        logger.info("Seeded starting_balance for %s at $%.2f", state.date, current_balance)
        return True

    loss_pct = (state.starting_balance - current_balance) / state.starting_balance * Decimal("100")
    if loss_pct >= Decimal(str(max_loss_pct)):
        await trip_breaker(
            session,
            f"daily_loss_halt_pct exceeded ({loss_pct:.1f}% >= {max_loss_pct}% — "
            f"starting=${state.starting_balance:.2f} current=${current_balance:.2f})",
        )
        return False

    return True


async def trip_breaker(session: AsyncSession, reason: str) -> None:
    """Manually trip the circuit breaker."""
    state = await get_daily_state(session)
    state.halted = True
    await session.commit()
    logger.critical("CIRCUIT BREAKER TRIPPED: %s", reason)


async def reset_breaker(session: AsyncSession) -> None:
    """Reset the circuit breaker for today."""
    state = await get_daily_state(session)
    state.halted = False
    await session.commit()
    logger.info("Circuit breaker reset for %s", state.date)


