"""Tests for simulation/dry_run_runner.py."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.simulation.dry_run_runner import load_fixture, run_directory, run_fixture
from app.state.models import Wallet


@pytest.fixture
def fixture_path(tmp_path):
    payload = [
        {
            "signature": "dryrun1",
            "type": "SWAP",
            "accountData": [
                {"account": "WhaleDry1111111111111111111111111111111111"}
            ],
            "tokenTransfers": [
                {
                    "fromUserAccount": "DEX",
                    "toUserAccount": "WhaleDry1111111111111111111111111111111111",
                    "mint": "TokenDry1111111111111111111111111111111111",
                    "tokenAmount": 5000,
                }
            ],
            "nativeTransfers": [],
        }
    ]
    p = tmp_path / "test_buy.json"
    p.write_text(json.dumps(payload))
    return p


async def test_load_fixture(fixture_path) -> None:
    data = load_fixture(fixture_path)
    assert isinstance(data, list)
    assert data[0]["signature"] == "dryrun1"


async def test_run_fixture(fixture_path, session) -> None:
    wallet = Wallet(address="WhaleDry1111111111111111111111111111111111", active=True)
    session.add(wallet)
    await session.commit()

    mock_profile = type("obj", (object,), {
        "token_mint": "TokenDry1111111111111111111111111111111111",
        "market_cap": Decimal("1000000"),
        "liquidity_usd": Decimal("100000"),
        "volume_24h": Decimal("500000"),
        "price_usd": Decimal("1000"),
        "rugcheck_score": 200,
        "risks": [],
    })()

    with patch(
        "app.simulation.dry_run_runner.enrich_token", new_callable=AsyncMock
    ) as mock_enrich:
        mock_enrich.return_value = mock_profile
        results = await run_fixture(
            session, fixture_path, {"WhaleDry1111111111111111111111111111111111"}
        )

    assert len(results) == 1
    r = results[0]
    assert r["enriched"] is True
    assert r["screened"] is True
    assert r["passed_screen"] is True


async def test_run_directory(fixture_path, session) -> None:
    wallet = Wallet(address="WhaleDry1111111111111111111111111111111111", active=True)
    session.add(wallet)
    await session.commit()

    with patch(
        "app.simulation.dry_run_runner.enrich_token", new_callable=AsyncMock
    ) as mock_enrich:
        mock_enrich.return_value = None
        results = await run_directory(
            session, fixture_path.parent, {"WhaleDry1111111111111111111111111111111111"}
        )

    assert "test_buy.json" in results
    assert results["test_buy.json"][0]["enriched"] is False


async def test_run_directory_missing(session) -> None:
    results = await run_directory(session, Path("/nonexistent"), set())
    assert results == {}
