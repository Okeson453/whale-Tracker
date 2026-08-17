"""Alert digest.

Builds a daily summary (alerts sent, pass rate, executed trades, PnL)
instead of relying solely on per-event notifications. Read-only against
existing state — introduces no new execution or alerting side effects,
just a rollup message formatted for Telegram delivery via the existing
notification channel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.state.models import Alert, SwapEvent, Trade, TradeStatus

logger = logging.getLogger(__name__)


@dataclass
class DailyDigest:
    digest_date: date
    total_alerts: int = 0
    passed_alerts: int = 0
    executed_trades: int = 0
    confirmed_trades: int = 0
    failed_trades: int = 0
    total_usd_deployed: Decimal = Decimal("0")

    @property
    def pass_rate_pct(self) -> float:
        if self.total_alerts == 0:
            return 0.0
        return round(self.passed_alerts / self.total_alerts * 100, 2)


def _day_bounds(digest_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(digest_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(digest_date, time.max, tzinfo=timezone.utc)
    return start, end


async def build_daily_digest(session: AsyncSession, digest_date: date) -> DailyDigest:
    """Aggregate alerts and trades for *digest_date* (UTC) into a DailyDigest."""
    start, end = _day_bounds(digest_date)
    digest = DailyDigest(digest_date=digest_date)

    alert_result = await session.execute(
        select(Alert)
        .join(SwapEvent, Alert.swap_event_id == SwapEvent.id)
        .where(SwapEvent.detected_at >= start)
        .where(SwapEvent.detected_at <= end)
    )
    alerts = alert_result.scalars().all()
    digest.total_alerts = len(alerts)
    digest.passed_alerts = sum(1 for a in alerts if a.passed_screen)

    alert_ids = [a.id for a in alerts]
    if alert_ids:
        trade_result = await session.execute(
            select(Trade).where(Trade.alert_id.in_(alert_ids))
        )
        trades = trade_result.scalars().all()
        digest.executed_trades = len(trades)
        digest.confirmed_trades = sum(
            1 for t in trades if t.status == TradeStatus.confirmed.value
        )
        digest.failed_trades = sum(
            1 for t in trades if t.status == TradeStatus.failed.value
        )
        digest.total_usd_deployed = sum(
            (t.usd_value for t in trades if t.usd_value), Decimal("0")
        )

    logger.info(
        "Daily digest for %s: %d alerts (%d passed), %d trades",
        digest_date,
        digest.total_alerts,
        digest.passed_alerts,
        digest.executed_trades,
    )
    return digest


def format_digest_message(digest: DailyDigest) -> str:
    """Render a DailyDigest as a Telegram-ready HTML message."""
    return (
        f"📊 <b>Daily Digest — {digest.digest_date.isoformat()}</b>\n"
        f"Alerts: {digest.total_alerts} (Passed: {digest.passed_alerts}, "
        f"{digest.pass_rate_pct}%)\n"
        f"Trades: {digest.executed_trades} "
        f"(Confirmed: {digest.confirmed_trades}, Failed: {digest.failed_trades})\n"
        f"USD Deployed: ${digest.total_usd_deployed:,.2f}"
    )
