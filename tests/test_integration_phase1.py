"""Phase 1 integration test: ingestion → enrichment end-to-end.

Posts a replayed webhook fixture to /webhook and verifies that:
- a SwapEvent row is persisted in swap_events
- enrichment_service.enrich_token is invoked for the token mint
- the HTTP response reflects the enriched result
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.state.db import get_db_session
from app.state.models import SwapEvent, TokenProfile, Wallet
from tests.fixtures.webhook_payloads import TOKEN_MINT, TRACKED_WALLET, buy_payload


@pytest.fixture
def client(session: AsyncSession):
    """Yield a TestClient with the DB session overridden."""
    async def _override():
        yield session

    app.dependency_overrides[get_db_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


async def test_webhook_persists_swap_event_and_enriches(
    client: TestClient, session: AsyncSession
) -> None:
    # Seed the tracked wallet
    wallet = Wallet(address=TRACKED_WALLET, label="test_whale", active=True)
    session.add(wallet)
    await session.commit()

    # Mock enrichment so we don't hit real APIs
    mock_profile = TokenProfile(
        token_mint=TOKEN_MINT,
        market_cap=Decimal("420000"),
        liquidity_usd=Decimal("85000"),
        volume_24h=Decimal("120000"),
        rugcheck_score=150,
        risks=["low_liquidity"],
    )

    with patch(
        "app.ingestion.webhook_receiver.enrich_token", new_callable=AsyncMock
    ) as mock_enrich:
        mock_enrich.return_value = mock_profile

        response = client.post("/webhook", json=[buy_payload()])

    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 1
    assert len(data["events"]) == 1

    evt = data["events"][0]
    assert evt["wallet"] == TRACKED_WALLET
    assert evt["token_mint"] == TOKEN_MINT
    assert evt["signature"] == "5Jv...buy"
    assert evt["enriched"] is True
    assert evt["market_cap"] == "420000"
    assert evt["liquidity_usd"] == "85000"

    # Verify enrichment was called once for this mint
    mock_enrich.assert_called_once()
    assert mock_enrich.call_args[0][0] == TOKEN_MINT

    # Verify SwapEvent persisted in DB
    result = await session.execute(
        select(SwapEvent).where(SwapEvent.signature == "5Jv...buy")
    )
    swap = result.scalar_one_or_none()
    assert swap is not None
    assert swap.token_mint == TOKEN_MINT
    assert swap.wallet_id == wallet.id
    assert swap.amount == Decimal("1250.5")


async def test_webhook_no_tracked_wallets(client: TestClient, session: AsyncSession) -> None:
    # No wallets seeded → empty result
    response = client.post("/webhook", json=[buy_payload()])
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 0
    assert data["events"] == []


async def test_webhook_sell_ignored(
    client: TestClient, session: AsyncSession
) -> None:
    from tests.fixtures.webhook_payloads import sell_payload

    wallet = Wallet(address=TRACKED_WALLET, label="test_whale", active=True)
    session.add(wallet)
    await session.commit()

    with patch(
        "app.ingestion.webhook_receiver.enrich_token", new_callable=AsyncMock
    ) as mock_enrich:
        response = client.post("/webhook", json=[sell_payload()])

    assert response.status_code == 200
    assert response.json()["processed"] == 0
    mock_enrich.assert_not_called()
