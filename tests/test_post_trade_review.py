"""Tests for analytics/post_trade_review.py."""

from __future__ import annotations

from decimal import Decimal

from app.analytics.post_trade_review import review_trade
from app.state.models import Alert, SwapEvent, Trade, Wallet


async def _seed_trade(session) -> Trade:
    wallet = Wallet(address="W1", active=True)
    session.add(wallet)
    await session.flush()

    event = SwapEvent(
        wallet_id=wallet.id, token_mint="TOKEN_A", amount=Decimal("100"), signature="sig1"
    )
    session.add(event)
    await session.flush()

    alert = Alert(swap_event_id=event.id, passed_screen=True)
    session.add(alert)
    await session.flush()

    trade = Trade(alert_id=alert.id, usd_value=Decimal("100"))
    session.add(trade)
    await session.commit()
    return trade


async def test_review_trade_within_thresholds_not_flagged(session) -> None:
    trade = await _seed_trade(session)
    review = await review_trade(
        session,
        trade.id,
        expected_slippage_bps=Decimal("100"),
        actual_slippage_bps=Decimal("150"),
        expected_fill_seconds=Decimal("3"),
        actual_fill_seconds=Decimal("4"),
    )
    assert review.flagged is False
    assert review.flag_reasons is None


async def test_review_trade_slippage_deviation_flagged(session) -> None:
    trade = await _seed_trade(session)
    review = await review_trade(
        session,
        trade.id,
        expected_slippage_bps=Decimal("100"),
        actual_slippage_bps=Decimal("500"),  # 400 bps deviation > 200 threshold
    )
    assert review.flagged is True
    assert any("slippage_deviation" in r for r in review.flag_reasons)


async def test_review_trade_fill_time_deviation_flagged(session) -> None:
    trade = await _seed_trade(session)
    review = await review_trade(
        session,
        trade.id,
        expected_fill_seconds=Decimal("2"),
        actual_fill_seconds=Decimal("10"),  # 8s deviation > 5s threshold
    )
    assert review.flagged is True
    assert any("fill_time_deviation" in r for r in review.flag_reasons)


async def test_review_trade_missing_data_not_flagged(session) -> None:
    trade = await _seed_trade(session)
    review = await review_trade(session, trade.id)
    assert review.flagged is False
