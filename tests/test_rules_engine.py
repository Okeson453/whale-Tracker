"""Tests for screening/rules_engine.py — each rule independently."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.screening.rules_engine import (
    rule_max_market_cap,
    rule_max_rugcheck_score,
    rule_min_buy_usd,
    rule_min_liquidity,
    screen_event,
)
from app.state.models import SwapEvent, TokenProfile


@pytest.fixture
def profile() -> TokenProfile:
    return TokenProfile(
        token_mint="TestMint111111111111111111111111111111111111",
        market_cap=Decimal("1000000"),
        liquidity_usd=Decimal("100000"),
        volume_24h=Decimal("500000"),
        price_usd=Decimal("0.001"),
        rugcheck_score=200,
        risks=[],
    )


@pytest.fixture
def event() -> SwapEvent:
    return SwapEvent(
        wallet_id="wallet-1",
        token_mint="TestMint111111111111111111111111111111111111",
        amount=Decimal("1000000"),
        signature="sig1",
    )


class TestRuleMaxMarketCap:
    def test_pass(self, profile: TokenProfile) -> None:
        assert rule_max_market_cap(profile) is None

    def test_fail(self, profile: TokenProfile) -> None:
        profile.market_cap = Decimal("6000000")
        reason = rule_max_market_cap(profile)
        assert reason is not None
        assert "market_cap_too_high" in reason

    def test_missing(self, profile: TokenProfile) -> None:
        profile.market_cap = None
        reason = rule_max_market_cap(profile)
        assert reason == "missing_market_cap"


class TestRuleMinLiquidity:
    def test_pass(self, profile: TokenProfile) -> None:
        assert rule_min_liquidity(profile) is None

    def test_fail(self, profile: TokenProfile) -> None:
        profile.liquidity_usd = Decimal("10000")
        reason = rule_min_liquidity(profile)
        assert reason is not None
        assert "liquidity_too_low" in reason

    def test_missing(self, profile: TokenProfile) -> None:
        profile.liquidity_usd = None
        reason = rule_min_liquidity(profile)
        assert reason == "missing_liquidity"


class TestRuleMaxRugcheckScore:
    def test_pass(self, profile: TokenProfile) -> None:
        assert rule_max_rugcheck_score(profile) is None

    def test_fail(self, profile: TokenProfile) -> None:
        profile.rugcheck_score = 600
        reason = rule_max_rugcheck_score(profile)
        assert reason is not None
        assert "rugcheck_score_too_high" in reason

    def test_missing(self, profile: TokenProfile) -> None:
        profile.rugcheck_score = None
        reason = rule_max_rugcheck_score(profile)
        assert reason == "missing_rugcheck_score"


class TestRuleMinBuyUsd:
    def test_pass(self, event: SwapEvent, profile: TokenProfile) -> None:
        assert rule_min_buy_usd(event, profile) is None

    def test_fail(self, event: SwapEvent, profile: TokenProfile) -> None:
        event.amount = Decimal("100")
        reason = rule_min_buy_usd(event, profile)
        assert reason is not None
        assert "buy_too_small" in reason

    def test_missing_price(self, event: SwapEvent, profile: TokenProfile) -> None:
        profile.price_usd = None
        reason = rule_min_buy_usd(event, profile)
        assert reason == "missing_price_for_buy_size"


class TestScreenEvent:
    def test_pass(self, event: SwapEvent, profile: TokenProfile) -> None:
        result = screen_event(event, profile)
        assert result.passed is True
        assert result.reasons == []

    def test_skip_multiple_reasons(self, event: SwapEvent, profile: TokenProfile) -> None:
        profile.market_cap = Decimal("6000000")
        profile.liquidity_usd = Decimal("10000")
        result = screen_event(event, profile)
        assert result.passed is False
        assert len(result.reasons) == 2
