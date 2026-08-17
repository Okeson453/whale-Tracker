"""Tests for execution/whitelist.py."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.execution.whitelist import get_max_auto_position_usd, should_auto_execute
from app.analytics.wallet_performance import record_alert_outcome
from app.state.models import Wallet


@pytest.fixture
async def wallet(session):
    w = Wallet(address="WhitelistWallet1111111111111111111111111111", active=True)
    session.add(w)
    await session.commit()
    return w


async def test_should_auto_execute_no_scorecard(session) -> None:
    ok, reason = await should_auto_execute(session, "nonexistent")
    assert ok is False
    assert "no scorecard" in reason


async def test_should_auto_execute_insufficient_alerts(session, wallet) -> None:
    for _ in range(5):
        await record_alert_outcome(session, wallet.id, passed_screen=True)
    ok, reason = await should_auto_execute(session, wallet.id)
    assert ok is False
    assert "insufficient alerts" in reason


async def test_should_auto_execute_low_pass_rate(session, wallet) -> None:
    for _ in range(25):
        await record_alert_outcome(session, wallet.id, passed_screen=False)
    ok, reason = await should_auto_execute(session, wallet.id)
    assert ok is False
    assert "pass rate too low" in reason


async def test_should_auto_execute_qualifies(session, wallet) -> None:
    for _ in range(25):
        await record_alert_outcome(session, wallet.id, passed_screen=True)
    ok, reason = await should_auto_execute(session, wallet.id)
    assert ok is True
    assert reason is None


def test_get_max_auto_position_usd() -> None:
    assert get_max_auto_position_usd() == Decimal("100")
