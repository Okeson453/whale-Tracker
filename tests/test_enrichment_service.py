"""Tests for enrichment_service — verify None on any API failure."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.enrichment.enrichment_service import enrich_token
from app.state.models import TokenProfile


TOKEN_MINT = "TestMint111111111111111111111111111111111111"


@pytest.fixture
def mock_price():
    with patch("app.enrichment.enrichment_service.get_price", new_callable=AsyncMock) as m:
        m.return_value = Decimal("0.42")
        yield m


@pytest.fixture
def mock_dex():
    with patch(
        "app.enrichment.enrichment_service.get_token_data", new_callable=AsyncMock
    ) as m:
        m.return_value = {
            "market_cap": Decimal("420000"),
            "liquidity_usd": Decimal("85000"),
            "volume_24h": Decimal("120000"),
        }
        yield m


@pytest.fixture
def mock_rug():
    with patch(
        "app.enrichment.enrichment_service.get_report", new_callable=AsyncMock
    ) as m:
        m.return_value = {"score": 150, "risks": ["low_liquidity"]}
        yield m


async def test_enrich_success(
    mock_price: AsyncMock, mock_dex: AsyncMock, mock_rug: AsyncMock, session: AsyncSession
) -> None:
    profile = await enrich_token(TOKEN_MINT, session)
    assert profile is not None
    assert isinstance(profile, TokenProfile)
    assert profile.token_mint == TOKEN_MINT
    assert profile.market_cap == Decimal("420000")
    assert profile.liquidity_usd == Decimal("85000")
    assert profile.volume_24h == Decimal("120000")
    assert profile.rugcheck_score == 150
    assert profile.risks == ["low_liquidity"]


async def test_enrich_price_failure(
    mock_price: AsyncMock, mock_dex: AsyncMock, mock_rug: AsyncMock, session: AsyncSession
) -> None:
    mock_price.return_value = None
    profile = await enrich_token(TOKEN_MINT, session)
    assert profile is None


async def test_enrich_dex_failure(
    mock_price: AsyncMock, mock_dex: AsyncMock, mock_rug: AsyncMock, session: AsyncSession
) -> None:
    mock_dex.return_value = None
    profile = await enrich_token(TOKEN_MINT, session)
    assert profile is None


async def test_enrich_rug_failure(
    mock_price: AsyncMock, mock_dex: AsyncMock, mock_rug: AsyncMock, session: AsyncSession
) -> None:
    mock_rug.return_value = None
    profile = await enrich_token(TOKEN_MINT, session)
    assert profile is None


async def test_enrich_exception_in_client(
    mock_price: AsyncMock, mock_dex: AsyncMock, mock_rug: AsyncMock, session: AsyncSession
) -> None:
    mock_dex.side_effect = TimeoutError("DexScreener timeout")
    profile = await enrich_token(TOKEN_MINT, session)
    assert profile is None
