"""Tests for notification/alert_digest.py."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from app.notification.alert_digest import build_daily_digest, format_digest_message
from app.state.models import Alert, SwapEvent, Trade, TradeStatus, Wallet


async def _seed(session, digest_date: date, passed: bool, trade_status: str | None, usd: Decimal | None):
    wallet = Wallet(address=f"W-{digest_date}-{passed}-{trade_status}", active=True)
    session.add(wallet)
    await session.flush()

    detected_at = datetime.combine(digest_date, datetime.min.time(), tzinfo=timezone.utc)
    event = SwapEvent(
        wallet_id=wallet.id,
        token_mint="TOKEN_A",
        amount=Decimal("10"),
        signature=f"sig-{wallet.id}",
        detected_at=detected_at,
    )
    session.add(event)
    await session.flush()

    alert = Alert(swap_event_id=event.id, passed_screen=passed)
    session.add(alert)
    await session.flush()

    if trade_status is not None:
        trade = Trade(alert_id=alert.id, usd_value=usd, status=trade_status)
        session.add(trade)

    await session.commit()


async def test_build_daily_digest_counts_alerts_and_trades(session) -> None:
    today = date(2026, 8, 17)
    await _seed(session, today, passed=True, trade_status=TradeStatus.confirmed.value, usd=Decimal("100"))
    await _seed(session, today, passed=True, trade_status=TradeStatus.failed.value, usd=Decimal("50"))
    await _seed(session, today, passed=False, trade_status=None, usd=None)

    digest = await build_daily_digest(session, today)
    assert digest.total_alerts == 3
    assert digest.passed_alerts == 2
    assert digest.executed_trades == 2
    assert digest.confirmed_trades == 1
    assert digest.failed_trades == 1
    assert digest.total_usd_deployed == Decimal("150")
    assert digest.pass_rate_pct == 66.67


async def test_build_daily_digest_excludes_other_days(session) -> None:
    today = date(2026, 8, 17)
    yesterday = date(2026, 8, 16)
    await _seed(session, yesterday, passed=True, trade_status=None, usd=None)

    digest = await build_daily_digest(session, today)
    assert digest.total_alerts == 0


def test_format_digest_message_includes_key_fields() -> None:
    from app.notification.alert_digest import DailyDigest

    digest = DailyDigest(
        digest_date=date(2026, 8, 17),
        total_alerts=5,
        passed_alerts=3,
        executed_trades=2,
        confirmed_trades=2,
        failed_trades=0,
        total_usd_deployed=Decimal("200.00"),
    )
    msg = format_digest_message(digest)
    assert "2026-08-17" in msg
    assert "200.00" in msg
