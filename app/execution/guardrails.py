"""Execution guardrails — highest-scrutiny module in the project.

Each guardrail is an independently testable function.
Fail-closed: any check that cannot be evaluated blocks the trade.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.config import yaml_settings
from app.execution.pricing import get_wallet_usd_value
from app.execution.quote_service import get_quote
from app.state.models import TokenProfile

logger = logging.getLogger(__name__)


def check_slippage(quote: dict[str, Any]) -> str | None:
    """Return skip reason if quoted slippage exceeds the configured cap.

    Jupiter quotes include ``priceImpactPct``; we treat that as the
    effective slippage indicator.
    """
    thresholds = yaml_settings.execution
    max_slippage_bps = thresholds.get("max_slippage_bps")
    if max_slippage_bps is None:
        return None

    price_impact = quote.get("priceImpactPct")
    if price_impact is None:
        return "missing_price_impact"

    try:
        # Jupiter returns priceImpactPct as a percentage string (e.g. "0.5" = 0.5%)
        impact_bps = Decimal(str(price_impact)) * Decimal("100")
    except Exception:
        return "unparseable_price_impact"

    if impact_bps > Decimal(str(max_slippage_bps)):
        return f"slippage_too_high ({impact_bps:.0f} bps > {max_slippage_bps})"
    return None


async def check_position_cap(
    current_positions_usd: Decimal, new_trade_usd: Decimal
) -> str | None:
    """Return skip reason if this trade would exceed the position cap.

    *current_positions_usd* is the sum of all open position values
    (see ``execution/position_exposure.py``). *new_trade_usd* is the USD
    value of the proposed trade. The cap itself is a percentage of the
    trading wallet's actual on-chain SOL balance, fetched fresh — not a
    nominal or assumed balance.
    """
    thresholds = yaml_settings.execution
    cap_pct = thresholds.get("position_cap_pct")
    if cap_pct is None:
        return None

    wallet_usd = await get_wallet_usd_value()
    if wallet_usd is None:
        # Fail closed: can't verify capacity, so don't allow the trade.
        return "wallet_balance_unavailable"

    cap_usd = wallet_usd * Decimal(str(cap_pct)) / Decimal("100")
    projected = current_positions_usd + new_trade_usd
    if projected > cap_usd:
        return (
            f"position_cap_exceeded (${projected:.2f} projected > "
            f"${cap_usd:.2f} cap = {cap_pct}% of ${wallet_usd:.2f} wallet)"
        )
    return None


async def check_honeypot(token_mint: str) -> str | None:
    """Re-check that a sell route exists before buying.

    Requests a Jupiter quote in the *sell* direction (token → SOL).
    If Jupiter returns no route, treat as honeypot.
    """
    from app.execution.quote_service import WSOL_MINT

    # Use a tiny amount for the sell simulation (1 unit of token)
    try:
        quote = await get_quote(
            output_mint=WSOL_MINT,
            amount_lamports=1,
            slippage_bps=1000,
            input_mint=token_mint,
        )
    except Exception as exc:
        logger.warning("Honeypot check API failure for %s: %s", token_mint, exc)
        return "honeypot_check_api_failure"

    if quote is None:
        return "honeypot_detected_no_sell_route"
    return None


def check_circuit_breaker(halted: bool) -> str | None:
    """Return skip reason if the circuit breaker is tripped."""
    if halted:
        return "circuit_breaker_halted"
    return None


async def run_all_guardrails(
    token_mint: str,
    quote: dict[str, Any],
    halted: bool,
    session: Any | None = None,
    new_trade_usd: Decimal | None = None,
) -> list[str]:
    """Run every guardrail and return a list of blocking reasons.

    An empty list means all guardrails passed and the trade may proceed.
    *session* and *new_trade_usd* are required for the position-cap check
    to run for real; when either is omitted (e.g. a sell, which doesn't
    add new exposure) the cap check is skipped rather than faked.
    """
    reasons: list[str] = []

    cb = check_circuit_breaker(halted)
    if cb:
        reasons.append(cb)

    slippage = check_slippage(quote)
    if slippage:
        reasons.append(slippage)

    honey = await check_honeypot(token_mint)
    if honey:
        reasons.append(honey)

    if session is not None and new_trade_usd is not None:
        from app.execution.position_exposure import get_open_positions_usd

        current_positions_usd = await get_open_positions_usd(session)
        pos = await check_position_cap(current_positions_usd, new_trade_usd)
        if pos:
            reasons.append(pos)

    if reasons:
        logger.warning("Guardrails blocked trade for %s: %s", token_mint, reasons)
    else:
        logger.info("All guardrails passed for %s", token_mint)

    return reasons
