"""Sum of USD value currently deployed across open copy-trade positions.

Feeds guardrails.check_position_cap so the cap is checked against real
exposure, not a placeholder.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.state.models import Position, PositionStatus


async def get_open_positions_usd(session: AsyncSession) -> Decimal:
    """Sum of ``entry_usd_value`` across all currently-open positions.

    Positions opened before entry_usd_value was populated (or opened via
    a path that couldn't price the trade) contribute 0 — they don't
    silently inflate or deflate the cap check, but note that means real
    exposure could be understated if such rows exist; check for NULL
    entry_usd_value rows if this number looks suspiciously low.
    """
    result = await session.execute(
        select(func.coalesce(func.sum(Position.entry_usd_value), Decimal("0"))).where(
            Position.status == PositionStatus.open.value
        )
    )
    total = result.scalar_one()
    return Decimal(total) if total is not None else Decimal("0")
