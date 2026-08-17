"""Screening rules engine — one function per rule, thresholds from settings.yaml.

Fail-closed: any missing field required by a rule causes a SKIP.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.config import yaml_settings
from app.ingestion.tx_parser import SwapEvent
from app.screening.rules_models import ScreeningResult
from app.state.models import TokenProfile

logger = logging.getLogger(__name__)


def _get_thresholds() -> dict[str, Any]:
    return yaml_settings.screening


def rule_max_market_cap(profile: TokenProfile) -> str | None:
    """Return skip reason if market cap exceeds threshold."""
    thresholds = _get_thresholds()
    max_mc = thresholds.get("max_market_cap_usd")
    if max_mc is None:
        return None
    if profile.market_cap is None:
        return "missing_market_cap"
    if profile.market_cap > Decimal(str(max_mc)):
        return f"market_cap_too_high ({profile.market_cap} > {max_mc})"
    return None


def rule_min_liquidity(profile: TokenProfile) -> str | None:
    """Return skip reason if liquidity is below floor."""
    thresholds = _get_thresholds()
    min_liq = thresholds.get("min_liquidity_usd")
    if min_liq is None:
        return None
    if profile.liquidity_usd is None:
        return "missing_liquidity"
    if profile.liquidity_usd < Decimal(str(min_liq)):
        return f"liquidity_too_low ({profile.liquidity_usd} < {min_liq})"
    return None


def rule_max_rugcheck_score(profile: TokenProfile) -> str | None:
    """Return skip reason if RugCheck score exceeds threshold."""
    thresholds = _get_thresholds()
    max_score = thresholds.get("max_rugcheck_score")
    if max_score is None:
        return None
    if profile.rugcheck_score is None:
        return "missing_rugcheck_score"
    if profile.rugcheck_score > int(max_score):
        return f"rugcheck_score_too_high ({profile.rugcheck_score} > {max_score})"
    return None


def rule_min_buy_usd(event: SwapEvent, profile: TokenProfile) -> str | None:
    """Return skip reason if the buy size (amount * price) is below threshold."""
    thresholds = _get_thresholds()
    min_buy = thresholds.get("min_buy_usd")
    if min_buy is None:
        return None
    if profile.price_usd is None:
        return "missing_price_for_buy_size"
    buy_usd = event.amount * profile.price_usd
    if buy_usd < Decimal(str(min_buy)):
        return f"buy_too_small ({buy_usd} < {min_buy})"
    return None


def screen_event(event: SwapEvent, profile: TokenProfile) -> ScreeningResult:
    """Apply all screening rules to a SwapEvent + TokenProfile.

    Returns PASS only if every rule returns None (no skip reason).
    """
    reasons: list[str] = []

    for rule in (rule_max_market_cap, rule_min_liquidity, rule_max_rugcheck_score):
        reason = rule(profile)
        if reason:
            reasons.append(reason)

    reason = rule_min_buy_usd(event, profile)
    if reason:
        reasons.append(reason)

    if reasons:
        logger.info("Screen SKIP for %s: %s", event.token_mint, reasons)
        return ScreeningResult(passed=False, reasons=reasons)

    logger.info("Screen PASS for %s", event.token_mint)
    return ScreeningResult(passed=True)
