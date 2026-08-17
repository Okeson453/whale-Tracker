"""Post-entry liquidity monitoring.

After a trade executes, liquidity is checked every 30 seconds for the
first 10 minutes — the window where a rug pull does the most damage,
since the position is freshest and the exit is least anticipated. If
liquidity drops more than the configured threshold from the entry
snapshot, this signals an emergency-exit condition.

This module only detects and signals — it does not build, sign, or
broadcast a sell itself. The caller supplies an async callback to invoke
when the threshold is breached, keeping this decoupled from whatever
exit-execution path exists (or doesn't yet) in the codebase. That
callback is still subject to the circuit breaker and any other guardrail
the caller chooses to apply before it — this module does not bypass
those on its own.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Awaitable, Callable

from app.enrichment.dexscreener_client import get_token_data

logger = logging.getLogger(__name__)

DEFAULT_CHECK_INTERVAL_SECONDS = 30
DEFAULT_MONITOR_DURATION_SECONDS = 10 * 60
DEFAULT_LIQUIDITY_DROP_THRESHOLD_PCT = Decimal("30")

EmergencyExitCallback = Callable[[str, Decimal, Decimal], Awaitable[None]]


@dataclass
class LiquidityMonitorResult:
    token_mint: str
    entry_liquidity_usd: Decimal
    lowest_observed_liquidity_usd: Decimal
    triggered_emergency_exit: bool
    checks_performed: int


async def monitor_post_entry_liquidity(
    token_mint: str,
    entry_liquidity_usd: Decimal,
    on_emergency_exit: EmergencyExitCallback | None = None,
    check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
    duration_seconds: float = DEFAULT_MONITOR_DURATION_SECONDS,
    drop_threshold_pct: Decimal = DEFAULT_LIQUIDITY_DROP_THRESHOLD_PCT,
    max_checks: int | None = None,
) -> LiquidityMonitorResult:
    """Poll liquidity for *token_mint* for *duration_seconds*, checking
    every *check_interval_seconds*.

    Calls *on_emergency_exit(token_mint, entry_liquidity_usd, current_liquidity_usd)*
    the first time liquidity drops more than *drop_threshold_pct* below
    entry, then keeps monitoring for the remainder of the window (a
    partial drop can precede a full rug). A DexScreener fetch failure
    during a check is logged and skipped — treated as "no new data this
    interval," not as a liquidity drop, since we can't distinguish a rug
    from a flaky API response from a single failed fetch.

    *check_interval_seconds* must be positive — at zero, elapsed time
    never advances and the loop would never terminate on its own. Pass
    *max_checks* to bound iteration count deterministically instead
    (used by tests to avoid depending on wall-clock timing).
    """
    if entry_liquidity_usd <= 0:
        raise ValueError("entry_liquidity_usd must be positive")
    if check_interval_seconds <= 0:
        raise ValueError("check_interval_seconds must be positive")

    elapsed = 0.0
    checks_performed = 0
    lowest_seen = entry_liquidity_usd
    already_triggered = False

    while elapsed < duration_seconds:
        if max_checks is not None and checks_performed >= max_checks:
            break

        await asyncio.sleep(check_interval_seconds)
        elapsed += check_interval_seconds
        checks_performed += 1

        data = await get_token_data(token_mint)
        if data is None or data.get("liquidity_usd") is None:
            logger.debug(
                "Liquidity check %d for %s: no data (skipping this interval)",
                checks_performed,
                token_mint,
            )
            continue

        current_liquidity = data["liquidity_usd"]
        if current_liquidity < lowest_seen:
            lowest_seen = current_liquidity

        drop_pct = (
            (entry_liquidity_usd - current_liquidity) / entry_liquidity_usd * Decimal("100")
        )

        logger.debug(
            "Liquidity check %d for %s: $%s (%.1f%% off entry)",
            checks_performed,
            token_mint,
            current_liquidity,
            float(drop_pct),
        )

        if drop_pct >= drop_threshold_pct and not already_triggered:
            already_triggered = True
            logger.warning(
                "Liquidity drop %.1f%% >= threshold %.1f%% for %s — "
                "signaling emergency exit",
                float(drop_pct),
                float(drop_threshold_pct),
                token_mint,
            )
            if on_emergency_exit is not None:
                await on_emergency_exit(token_mint, entry_liquidity_usd, current_liquidity)

    return LiquidityMonitorResult(
        token_mint=token_mint,
        entry_liquidity_usd=entry_liquidity_usd,
        lowest_observed_liquidity_usd=lowest_seen,
        triggered_emergency_exit=already_triggered,
        checks_performed=checks_performed,
    )
