"""Tests for execution/guardrails.py — each guardrail independently testable."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.execution.guardrails import (
    check_circuit_breaker,
    check_honeypot,
    check_position_cap,
    check_slippage,
    run_all_guardrails,
)


class TestCheckSlippage:
    def test_pass(self) -> None:
        quote = {"priceImpactPct": "0.02"}  # 0.02% = 2 bps
        assert check_slippage(quote) is None

    def test_fail(self) -> None:
        quote = {"priceImpactPct": "10.0"}  # 10% = 1000 bps
        reason = check_slippage(quote)
        assert reason is not None
        assert "slippage_too_high" in reason

    def test_missing(self) -> None:
        assert check_slippage({}) == "missing_price_impact"


class TestCheckCircuitBreaker:
    def test_pass(self) -> None:
        assert check_circuit_breaker(False) is None

    def test_fail(self) -> None:
        assert check_circuit_breaker(True) == "circuit_breaker_halted"


class TestCheckPositionCap:
    async def test_passes_within_cap(self) -> None:
        with patch(
            "app.execution.guardrails.get_wallet_usd_value", new_callable=AsyncMock
        ) as mock_wallet, patch("app.execution.guardrails.yaml_settings") as mock_settings:
            mock_settings.execution = {"position_cap_pct": 10}
            mock_wallet.return_value = Decimal("1000")  # 10% cap = $100
            assert await check_position_cap(Decimal("50"), Decimal("40")) is None

    async def test_blocks_over_cap(self) -> None:
        with patch(
            "app.execution.guardrails.get_wallet_usd_value", new_callable=AsyncMock
        ) as mock_wallet, patch("app.execution.guardrails.yaml_settings") as mock_settings:
            mock_settings.execution = {"position_cap_pct": 10}
            mock_wallet.return_value = Decimal("1000")  # 10% cap = $100
            reason = await check_position_cap(Decimal("80"), Decimal("50"))
            assert reason is not None
            assert "position_cap_exceeded" in reason

    async def test_fails_closed_when_balance_unavailable(self) -> None:
        with patch(
            "app.execution.guardrails.get_wallet_usd_value", new_callable=AsyncMock
        ) as mock_wallet, patch("app.execution.guardrails.yaml_settings") as mock_settings:
            mock_settings.execution = {"position_cap_pct": 10}
            mock_wallet.return_value = None
            assert await check_position_cap(Decimal("0"), Decimal("10")) == "wallet_balance_unavailable"

    async def test_no_cap_configured_passes(self) -> None:
        with patch("app.execution.guardrails.yaml_settings") as mock_settings:
            mock_settings.execution = {}
            assert await check_position_cap(Decimal("1000"), Decimal("500")) is None


class TestCheckHoneypot:
    async def test_pass(self) -> None:
        with patch(
            "app.execution.guardrails.get_quote", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"outAmount": "100"}
            assert await check_honeypot("SomeMint") is None

    async def test_fail_no_route(self) -> None:
        with patch(
            "app.execution.guardrails.get_quote", new_callable=AsyncMock
        ) as mock:
            mock.return_value = None
            reason = await check_honeypot("SomeMint")
            assert reason == "honeypot_detected_no_sell_route"

    async def test_api_failure(self) -> None:
        with patch(
            "app.execution.guardrails.get_quote", new_callable=AsyncMock
        ) as mock:
            mock.side_effect = TimeoutError("API timeout")
            reason = await check_honeypot("SomeMint")
            assert reason == "honeypot_check_api_failure"


class TestRunAllGuardrails:
    async def test_all_pass(self) -> None:
        with patch(
            "app.execution.guardrails.get_quote", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"outAmount": "100"}
            reasons = await run_all_guardrails(
                "SomeMint",
                {"priceImpactPct": "0.01"},
                halted=False,
            )
            assert reasons == []

    async def test_blocked_by_slippage(self) -> None:
        with patch(
            "app.execution.guardrails.get_quote", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"outAmount": "100"}
            reasons = await run_all_guardrails(
                "SomeMint",
                {"priceImpactPct": "50.0"},
                halted=False,
            )
            assert any("slippage_too_high" in r for r in reasons)

    async def test_blocked_by_circuit_breaker(self) -> None:
        with patch(
            "app.execution.guardrails.get_quote", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"outAmount": "100"}
            reasons = await run_all_guardrails(
                "SomeMint",
                {"priceImpactPct": "0.01"},
                halted=True,
            )
            assert any("circuit_breaker_halted" in r for r in reasons)
