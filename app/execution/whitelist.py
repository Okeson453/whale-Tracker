"""Auto-execute whitelist — proven wallets skip the human approval gate.

Only activates when a wallet's scorecard meets explicitly configured
thresholds (win-rate + minimum observed alerts). Position sizes are
capped per-wallet to limit blast radius.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.wallet_performance import get_wallet_scorecard
from app.config import yaml_settings

logger = logging.getLogger(__name__)


def _thresholds() -> dict[str, Any]:
    return yaml_settings.whitelist


async def should_auto_execute(
    session: AsyncSession,
    wallet_id: str,
) -> tuple[bool, str | None]:
    """Determine whether a wallet qualifies for auto-execution.

    Returns (should_execute, reason_if_not).
    """
    thresholds = _thresholds()
    min_pass_rate = thresholds.get("min_pass_rate_pct")
    min_alerts = thresholds.get("min_observed_alerts")

    if min_pass_rate is None or min_alerts is None:
        return False, "whitelist thresholds not configured"

    scorecard = await get_wallet_scorecard(session, wallet_id)
    if scorecard is None:
        return False, "no scorecard available"

    if scorecard.total_alerts < int(min_alerts):
        return (
            False,
            f"insufficient alerts ({scorecard.total_alerts} < {min_alerts})",
        )

    if scorecard.pass_rate < float(min_pass_rate):
        return (
            False,
            f"pass rate too low ({scorecard.pass_rate:.1f}% < {min_pass_rate}%)",
        )

    logger.info(
        "Wallet %s qualifies for auto-execute (pass_rate=%.1f%%, alerts=%d)",
        wallet_id,
        scorecard.pass_rate,
        scorecard.total_alerts,
    )
    return True, None


def get_max_auto_position_usd() -> Decimal:
    """Return the per-wallet auto-execute position cap from config."""
    raw = _thresholds().get("max_auto_position_usd", 100)
    return Decimal(str(raw))
