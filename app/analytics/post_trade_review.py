"""Post-trade auto-review.

Flags any trade where actual slippage or fill time deviated significantly
from the guardrail-time estimate, so it surfaces for manual review instead
of silently blending into the trade history. This does not judge whether
a trade was profitable — only whether execution behaved as guardrails
expected it to.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import yaml_settings
from app.state.models import PostTradeReview

logger = logging.getLogger(__name__)


def _thresholds() -> dict[str, Any]:
    return yaml_settings.post_trade_review


def _evaluate(
    expected_slippage_bps: Decimal | None,
    actual_slippage_bps: Decimal | None,
    expected_fill_seconds: Decimal | None,
    actual_fill_seconds: Decimal | None,
) -> list[str]:
    """Return a list of flag reasons — empty if execution matched expectations."""
    thresholds = _thresholds()
    slippage_threshold = Decimal(str(thresholds.get("slippage_deviation_bps_threshold", 200)))
    fill_time_threshold = Decimal(str(thresholds.get("fill_time_deviation_seconds_threshold", 5)))

    reasons: list[str] = []

    if expected_slippage_bps is not None and actual_slippage_bps is not None:
        deviation = abs(actual_slippage_bps - expected_slippage_bps)
        if deviation > slippage_threshold:
            reasons.append(
                f"slippage_deviation ({deviation:.0f} bps > {slippage_threshold} bps)"
            )

    if expected_fill_seconds is not None and actual_fill_seconds is not None:
        deviation = abs(actual_fill_seconds - expected_fill_seconds)
        if deviation > fill_time_threshold:
            reasons.append(
                f"fill_time_deviation ({deviation:.1f}s > {fill_time_threshold}s)"
            )

    return reasons


async def review_trade(
    session: AsyncSession,
    trade_id: str,
    expected_slippage_bps: Decimal | None = None,
    actual_slippage_bps: Decimal | None = None,
    expected_fill_seconds: Decimal | None = None,
    actual_fill_seconds: Decimal | None = None,
) -> PostTradeReview:
    """Compare a trade's actual execution against its guardrail-time
    estimate and persist a review record, flagged if deviation exceeds
    the configured thresholds.
    """
    reasons = _evaluate(
        expected_slippage_bps,
        actual_slippage_bps,
        expected_fill_seconds,
        actual_fill_seconds,
    )

    review = PostTradeReview(
        trade_id=trade_id,
        expected_slippage_bps=expected_slippage_bps,
        actual_slippage_bps=actual_slippage_bps,
        expected_fill_seconds=expected_fill_seconds,
        actual_fill_seconds=actual_fill_seconds,
        flagged=bool(reasons),
        flag_reasons=reasons or None,
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)

    if reasons:
        logger.warning("Trade %s flagged for review: %s", trade_id, reasons)
    else:
        logger.debug("Trade %s matched execution expectations", trade_id)

    return review
