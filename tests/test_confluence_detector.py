"""Tests for analytics/confluence_detector.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.analytics.confluence_detector import check_confluence, get_recent_confluence
from app.state.models import ConfluenceEvent


TOKEN = "MintA111111111111111111111111111111111111"


async def test_check_confluence_first_buy_creates_event(session) -> None:
    result = await check_confluence(session, TOKEN, "Wallet1")
    assert result is not None
    assert result.token_mint == TOKEN
    assert result.wallet_addresses == ["Wallet1"]
    assert result.alert_count == 1


async def test_check_confluence_second_wallet_boosts(session) -> None:
    await check_confluence(session, TOKEN, "Wallet1")
    result = await check_confluence(session, TOKEN, "Wallet2")
    assert result is not None
    assert "Wallet1" in result.wallet_addresses
    assert "Wallet2" in result.wallet_addresses
    assert result.alert_count == 2
    assert result.confidence_boost is True


async def test_check_confluence_same_wallet_no_duplicate(session) -> None:
    await check_confluence(session, TOKEN, "Wallet1")
    result = await check_confluence(session, TOKEN, "Wallet1")
    assert result.wallet_addresses == ["Wallet1"]
    assert result.alert_count == 1


async def test_get_recent_confluence_meets_threshold(session) -> None:
    await check_confluence(session, TOKEN, "Wallet1")
    await check_confluence(session, TOKEN, "Wallet2")
    result = await get_recent_confluence(session, TOKEN, min_wallets=2)
    assert result is not None
    assert len(result.wallet_addresses) == 2


async def test_get_recent_confluence_below_threshold(session) -> None:
    await check_confluence(session, TOKEN, "Wallet1")
    result = await get_recent_confluence(session, TOKEN, min_wallets=2)
    assert result is None


async def test_get_recent_confluence_expired(session) -> None:
    # Create an old event manually
    old = ConfluenceEvent(
        token_mint=TOKEN,
        wallet_addresses=["Wallet1", "Wallet2"],
        first_seen_at=datetime.now(timezone.utc) - timedelta(seconds=1000),
        last_seen_at=datetime.now(timezone.utc) - timedelta(seconds=1000),
        alert_count=2,
    )
    session.add(old)
    await session.commit()

    result = await get_recent_confluence(session, TOKEN, min_wallets=2, window_seconds=300)
    assert result is None
