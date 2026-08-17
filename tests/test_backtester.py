"""Tests for simulation/backtester.py."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.simulation.backtester import format_report_summary, run_backtest
from app.state.models import Wallet


def _make_fixture(tmp_path: Path, name: str, wallet: str, mint: str, sig: str) -> None:
    payload = [
        {
            "signature": sig,
            "type": "SWAP",
            "accountData": [{"account": wallet}],
            "tokenTransfers": [
                {
                    "fromUserAccount": "DEX",
                    "toUserAccount": wallet,
                    "mint": mint,
                    "tokenAmount": 1000,
                }
            ],
            "nativeTransfers": [],
        }
    ]
    (tmp_path / name).write_text(json.dumps(payload))


async def test_run_backtest_aggregates_across_fixtures(tmp_path, session) -> None:
    wallet_addr = "WhaleBT1111111111111111111111111111111111"
    wallet = Wallet(address=wallet_addr, active=True)
    session.add(wallet)
    await session.commit()

    _make_fixture(tmp_path, "f1.json", wallet_addr, "MintA1111111111111111111111111111111111", "sigbt1")
    _make_fixture(tmp_path, "f2.json", wallet_addr, "MintB1111111111111111111111111111111111", "sigbt2")

    mock_profile = type("obj", (object,), {
        "token_mint": "x",
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
        report = await run_backtest(session, tmp_path, {wallet_addr})

    assert report.fixtures_run == 2
    assert report.total_events == 2
    assert report.passed_screen == 2
    assert report.pass_rate_pct == 100.0
    assert report.per_wallet_total_count[wallet_addr] == 2


async def test_run_backtest_tracks_skip_reasons(tmp_path, session) -> None:
    wallet_addr = "WhaleBT2222222222222222222222222222222222"
    wallet = Wallet(address=wallet_addr, active=True)
    session.add(wallet)
    await session.commit()

    _make_fixture(tmp_path, "f1.json", wallet_addr, "MintC1111111111111111111111111111111111", "sigbt3")

    with patch(
        "app.simulation.dry_run_runner.enrich_token", new_callable=AsyncMock
    ) as mock_enrich:
        mock_enrich.return_value = None  # enrichment failure -> not screened
        report = await run_backtest(session, tmp_path, {wallet_addr})

    assert report.total_events == 1
    assert report.enriched_events == 0
    assert report.passed_screen == 0


def test_format_report_summary_includes_pass_rate() -> None:
    from app.simulation.backtester import BacktestReport

    report = BacktestReport(fixtures_run=2, total_events=10, passed_screen=6)
    summary = format_report_summary(report)
    assert "60.0%" in summary
    assert "6/10" in summary
