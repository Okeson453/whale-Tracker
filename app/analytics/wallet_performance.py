"""Per-whale win-rate tracking and would-be PnL computation.

Logs every alert's outcome so wallets can be ranked by actual edge
before any capital is risked on them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.analytics_models import WalletScorecardDataclass
from app.config import yaml_settings
from app.state.models import Alert, SwapEvent, TokenProfile, Wallet, WalletScorecard

logger = logging.getLogger(__name__)


def _thresholds() -> dict:
    return yaml_settings.analytics


async def record_alert_outcome(
    session: AsyncSession,
    wallet_id: str,
    passed_screen: bool,
    price_at_alert: Decimal | None = None,
    current_price: Decimal | None = None,
) -> WalletScorecard:
    """Update a wallet's scorecard after an alert is processed.

    If both prices are provided, computes the would-be PnL for this alert.
    """
    result = await session.execute(
        select(WalletScorecard).where(WalletScorecard.wallet_id == wallet_id)
    )
    scorecard = result.scalar_one_or_none()
    if scorecard is None:
        scorecard = WalletScorecard(
            wallet_id=wallet_id,
            total_alerts=0,
            passed_alerts=0,
            would_be_pnl=Decimal("0"),
        )
        session.add(scorecard)
        await session.flush()

    scorecard.total_alerts += 1
    if passed_screen:
        scorecard.passed_alerts += 1

    if price_at_alert is not None and current_price is not None and price_at_alert > 0:
        return_pct = (current_price - price_at_alert) / price_at_alert * Decimal("100")
        pnl = current_price - price_at_alert  # simplified: per-token unit PnL
        scorecard.would_be_pnl += pnl

        # Rolling average return
        if scorecard.avg_return_pct is None:
            scorecard.avg_return_pct = return_pct
        else:
            n = Decimal(str(scorecard.total_alerts))
            scorecard.avg_return_pct = (
                scorecard.avg_return_pct * (n - Decimal("1")) + return_pct
            ) / n

    scorecard.last_alert_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(scorecard)
    logger.debug(
        "Scorecard updated for wallet %s — total=%d passed=%d",
        wallet_id,
        scorecard.total_alerts,
        scorecard.passed_alerts,
    )
    return scorecard


async def get_wallet_scorecard(
    session: AsyncSession, wallet_id: str
) -> WalletScorecardDataclass | None:
    """Return a read-only scorecard view for a wallet, or None if never scored."""
    result = await session.execute(
        select(WalletScorecard, Wallet.address)
        .join(Wallet, WalletScorecard.wallet_id == Wallet.id)
        .where(WalletScorecard.wallet_id == wallet_id)
    )
    row = result.one_or_none()
    if row is None:
        return None

    sc, addr = row
    return WalletScorecardDataclass(
        wallet_id=sc.wallet_id,
        wallet_address=addr,
        total_alerts=sc.total_alerts,
        passed_alerts=sc.passed_alerts,
        would_be_pnl=sc.would_be_pnl,
        avg_return_pct=sc.avg_return_pct,
        last_alert_at=sc.last_alert_at,
        updated_at=sc.updated_at,
    )


async def rank_wallets(
    session: AsyncSession, min_alerts: int | None = None
) -> list[WalletScorecardDataclass]:
    """Return wallets sorted by would-be PnL (highest first).

    Filters to wallets with at least *min_alerts* observations.
    """
    if min_alerts is None:
        min_alerts = _thresholds().get("min_alerts_for_scorecard", 10)

    result = await session.execute(
        select(WalletScorecard, Wallet.address)
        .join(Wallet, WalletScorecard.wallet_id == Wallet.id)
        .where(WalletScorecard.total_alerts >= min_alerts)
        .order_by(desc(WalletScorecard.would_be_pnl))
    )

    ranked: list[WalletScorecardDataclass] = []
    for sc, addr in result.all():
        ranked.append(
            WalletScorecardDataclass(
                wallet_id=sc.wallet_id,
                wallet_address=addr,
                total_alerts=sc.total_alerts,
                passed_alerts=sc.passed_alerts,
                would_be_pnl=sc.would_be_pnl,
                avg_return_pct=sc.avg_return_pct,
                last_alert_at=sc.last_alert_at,
                updated_at=sc.updated_at,
            )
        )
    return ranked
