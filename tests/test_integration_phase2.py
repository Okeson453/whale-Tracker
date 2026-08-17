"""Phase 2 integration test: screening → notification end-to-end.

A detected, enriched, passing buy should produce a correctly formatted
Telegram alert and cache the alert for callback handling.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.state.db import get_db_session
from app.state.models import Alert, TokenProfile, Wallet
from tests.fixtures.webhook_payloads import TOKEN_MINT, TRACKED_WALLET, buy_payload


@pytest.fixture
def client(session):
    async def _override():
        yield session

    app.dependency_overrides[get_db_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


async def test_passing_buy_creates_alert_and_caches(
    client, session
) -> None:
    """A buy that passes all screening rules creates an Alert row
    and caches the alert context for the callback handler."""
    wallet = Wallet(address=TRACKED_WALLET, label="test_whale", active=True)
    session.add(wallet)
    await session.commit()

    # Mock enrichment to return a profile that passes screening
    mock_profile = TokenProfile(
        token_mint=TOKEN_MINT,
        market_cap=Decimal("1000000"),   # under 5M cap
        liquidity_usd=Decimal("100000"),  # over 50K floor
        volume_24h=Decimal("500000"),
        price_usd=Decimal("1000"),  # buy_usd = 1250.5 * 1000 = 1.25M > 500 min
        rugcheck_score=200,               # under 500 max
        risks=[],
    )

    with patch(
        "app.ingestion.webhook_receiver.enrich_token", new_callable=AsyncMock
    ) as mock_enrich, patch(
        "app.ingestion.webhook_receiver.send_alert", new_callable=AsyncMock
    ) as mock_send, patch(
        "app.ingestion.webhook_receiver.cache_alert"
    ) as mock_cache:
        mock_enrich.return_value = mock_profile
        mock_send.return_value = True

        response = client.post("/webhook", json=[buy_payload()])

    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 1
    evt = data["events"][0]
    assert evt["screened"] is True
    assert evt["passed_screen"] is True
    assert evt["alert_id"] is not None

    # Verify Alert persisted in DB
    alert_id = evt["alert_id"]
    result = await session.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    assert alert is not None
    assert alert.passed_screen is True
    assert alert.skip_reasons is None

    # Verify Telegram alert was sent (called with positional args)
    mock_send.assert_called_once()
    call_args = mock_send.call_args.args
    assert call_args[5] == alert_id  # alert_id is the 6th positional arg

    # Verify alert was cached for callback handler
    mock_cache.assert_called_once()
    assert mock_cache.call_args[0][0] == alert_id


async def test_failing_buy_creates_skip_alert(
    client, session
) -> None:
    """A buy that fails screening creates an Alert with skip reasons
    and does NOT send a Telegram alert."""
    wallet = Wallet(address=TRACKED_WALLET, label="test_whale", active=True)
    session.add(wallet)
    await session.commit()

    # Mock enrichment to return a profile that FAILS screening
    mock_profile = TokenProfile(
        token_mint=TOKEN_MINT,
        market_cap=Decimal("6000000"),   # OVER 5M cap → fail
        liquidity_usd=Decimal("100000"),
        volume_24h=Decimal("500000"),
        price_usd=Decimal("1000"),  # buy_usd = 1250.5 * 1000 = 1.25M > 500 min
        rugcheck_score=200,
        risks=[],
    )

    with patch(
        "app.ingestion.webhook_receiver.enrich_token", new_callable=AsyncMock
    ) as mock_enrich, patch(
        "app.ingestion.webhook_receiver.send_alert", new_callable=AsyncMock
    ) as mock_send, patch(
        "app.ingestion.webhook_receiver.cache_alert"
    ) as mock_cache:
        mock_enrich.return_value = mock_profile

        response = client.post("/webhook", json=[buy_payload()])

    assert response.status_code == 200
    data = response.json()
    evt = data["events"][0]
    assert evt["screened"] is True
    assert evt["passed_screen"] is False
    assert evt["alert_id"] is not None

    # Verify Alert persisted with skip reasons
    alert_id = evt["alert_id"]
    result = await session.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    assert alert is not None
    assert alert.passed_screen is False
    assert alert.skip_reasons is not None
    assert any("market_cap_too_high" in r for r in alert.skip_reasons)

    # Telegram alert should NOT have been sent
    mock_send.assert_not_called()
    mock_cache.assert_not_called()
