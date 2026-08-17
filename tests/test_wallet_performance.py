"""Tests for analytics/wallet_performance.py."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.analytics.wallet_performance import (
    get_wallet_scorecard,
    rank_wallets,
    record_alert_outcome,
)
from app.state.models import Wallet, WalletScorecard


@pytest.fixture
async def wallet(session):
    w = Wallet(address="WhalePerf1111111111111111111111111111111111", active=True)
    session.add(w)
    await session.commit()
    return w


async def test_record_alert_outcome_creates_scorecard(session, wallet) -> None:
    sc = await record_alert_outcome(session, wallet.id, passed_screen=True)
    assert sc.wallet_id == wallet.id
    assert sc.total_alerts == 1
    assert sc.passed_alerts == 1


async def test_record_alert_outcome_updates_existing(session, wallet) -> None:
    await record_alert_outcome(session, wallet.id, passed_screen=True)
    sc = await record_alert_outcome(session, wallet.id, passed_screen=False)
    assert sc.total_alerts == 2
    assert sc.passed_alerts == 1


async def test_record_alert_outcome_computes_pnl(session, wallet) -> None:
    sc = await record_alert_outcome(
        session, wallet.id, passed_screen=True,
        price_at_alert=Decimal("1.00"), current_price=Decimal("1.50")
    )
    assert sc.would_be_pnl == Decimal("0.50")
    assert sc.avg_return_pct == Decimal("50.00")


async def test_get_wallet_scorecard_found(session, wallet) -> None:
    await record_alert_outcome(session, wallet.id, passed_screen=True)
    view = await get_wallet_scorecard(session, wallet.id)
    assert view is not None
    assert view.wallet_address == wallet.address
    assert view.pass_rate == 100.0


async def test_get_wallet_scorecard_not_found(session) -> None:
    view = await get_wallet_scorecard(session, "nonexistent")
    assert view is None


async def test_rank_wallets_sorted_by_pnl(session) -> None:
    w1 = Wallet(address="W1", active=True)
    w2 = Wallet(address="W2", active=True)
    session.add_all([w1, w2])
    await session.commit()

    # Seed scorecards with different PnL
    for _ in range(15):
        await record_alert_outcome(session, w1.id, passed_screen=True)
    sc1 = await record_alert_outcome(
        session, w1.id, passed_screen=True,
        price_at_alert=Decimal("1"), current_price=Decimal("10")
    )
    sc1.would_be_pnl = Decimal("100")
    await session.commit()

    for _ in range(15):
        await record_alert_outcome(session, w2.id, passed_screen=True)
    sc2 = await record_alert_outcome(
        session, w2.id, passed_screen=True,
        price_at_alert=Decimal("1"), current_price=Decimal("2")
    )
    sc2.would_be_pnl = Decimal("10")
    await session.commit()

    ranked = await rank_wallets(session, min_alerts=10)
    assert len(ranked) == 2
    assert ranked[0].wallet_id == w1.id  # higher PnL first
    assert ranked[1].wallet_id == w2.id


async def test_rank_wallets_filters_min_alerts(session, wallet) -> None:
    await record_alert_outcome(session, wallet.id, passed_screen=True)
    ranked = await rank_wallets(session, min_alerts=10)
    assert len(ranked) == 0
