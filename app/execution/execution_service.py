"""Shared buy/sell execution pipeline.

Both the human-approval callback (``notification/callback_handler.py``) and
the automated copy-trade path (``execution/copy_trade_engine.py``) route
through here, so there is exactly one place that talks to the quote,
guardrail, signing, and broadcast layers. Do not duplicate this logic
elsewhere — if the pipeline needs to change (a new guardrail, a different
broadcast strategy), it should change once, for every execution path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.execution.broadcaster import send_transaction
from app.execution.guardrails import check_circuit_breaker, check_honeypot, check_position_cap, check_slippage
from app.execution.pricing import get_sol_usd_price
from app.execution.position_exposure import get_open_positions_usd
from app.execution.quote_service import WSOL_MINT, get_quote
from app.execution.signer import get_public_key, sign_transaction
from app.execution.tx_builder import build_swap_tx
from app.state.circuit_breaker import check_daily_loss, check_max_trades, is_halted, record_trade

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    error: str | None = None
    reasons: list[str] | None = None
    signature: str | None = None
    quote: dict[str, Any] | None = None
    usd_value: Decimal | None = None


async def _preflight(session) -> str | None:
    """Circuit-breaker checks common to every trade, buy or sell.

    Sells intentionally still respect the daily trade-count limit and the
    halt flag: if the breaker has tripped because of losses, letting exits
    still fire but blocking entries is a defensible design too, but for
    this project fail-closed on both sides is the safer default — a halt
    means "stop touching the chain", not "stop buying but keep selling".
    """
    if await is_halted(session):
        return "circuit_breaker_halted"
    if not await check_max_trades(session):
        return "daily_trade_limit_reached"
    if not await check_daily_loss(session):
        return "circuit_breaker_halted"
    return None


async def execute_buy_swap(
    token_mint: str,
    amount_lamports: int,
    slippage_bps: int,
    session,
) -> ExecutionResult:
    """Quote → guardrails (incl. honeypot + position cap) → build → sign → broadcast, SOL→token."""
    preflight_err = await _preflight(session)
    if preflight_err:
        logger.warning("Buy blocked pre-quote: %s", preflight_err)
        return ExecutionResult(ok=False, error=preflight_err)

    quote = await get_quote(token_mint, amount_lamports, slippage_bps)
    if quote is None:
        return ExecutionResult(ok=False, error="quote_failed")

    sol_price = await get_sol_usd_price()
    trade_usd = (
        (Decimal(amount_lamports) / Decimal(10**9)) * sol_price
        if sol_price is not None
        else None
    )

    halted = await is_halted(session)
    reasons: list[str] = []
    cb = check_circuit_breaker(halted)
    if cb:
        reasons.append(cb)
    slip = check_slippage(quote)
    if slip:
        reasons.append(slip)
    honey = await check_honeypot(token_mint)
    if honey:
        reasons.append(honey)
    if trade_usd is None:
        # Fail closed: can't price this trade, can't check it against the
        # position cap, so don't let it through silently uncapped.
        reasons.append("usd_pricing_unavailable")
    else:
        current_usd = await get_open_positions_usd(session)
        cap_reason = await check_position_cap(current_usd, trade_usd)
        if cap_reason:
            reasons.append(cap_reason)
    if reasons:
        logger.warning("Buy blocked by guardrails for %s: %s", token_mint, reasons)
        return ExecutionResult(ok=False, error="guardrails_blocked", reasons=reasons, quote=quote)

    return await _sign_and_broadcast(quote, session, usd_value=trade_usd)


async def execute_sell_swap(
    token_mint: str,
    amount_token_atoms: int,
    slippage_bps: int,
    session,
) -> ExecutionResult:
    """Quote → guardrails (no honeypot re-check — we're exiting) → build → sign → broadcast, token→SOL.

    Deliberately skips ``check_honeypot``: that guardrail exists to stop us
    from *entering* a position we cannot later exit. On the sell path we're
    already holding the token, so the only thing to check is that the
    route quote itself is usable (an inability to route the sell surfaces
    as ``quote_failed`` here rather than as a honeypot classification).
    """
    preflight_err = await _preflight(session)
    if preflight_err:
        logger.warning("Sell blocked pre-quote for %s: %s", token_mint, preflight_err)
        return ExecutionResult(ok=False, error=preflight_err)

    quote = await get_quote(
        output_mint=WSOL_MINT,
        amount_lamports=amount_token_atoms,
        slippage_bps=slippage_bps,
        input_mint=token_mint,
    )
    if quote is None:
        return ExecutionResult(ok=False, error="quote_failed")

    halted = await is_halted(session)
    reasons: list[str] = []
    cb = check_circuit_breaker(halted)
    if cb:
        reasons.append(cb)
    slip = check_slippage(quote)
    if slip:
        reasons.append(slip)
    if reasons:
        logger.warning("Sell blocked by guardrails for %s: %s", token_mint, reasons)
        return ExecutionResult(ok=False, error="guardrails_blocked", reasons=reasons, quote=quote)

    return await _sign_and_broadcast(quote, session)


async def _sign_and_broadcast(
    quote: dict[str, Any], session, usd_value: Decimal | None = None
) -> ExecutionResult:
    pubkey = get_public_key()
    if not pubkey:
        return ExecutionResult(ok=False, error="missing_public_key", quote=quote)

    swap_tx = await build_swap_tx(quote, pubkey)
    if not swap_tx:
        return ExecutionResult(ok=False, error="tx_build_failed", quote=quote)

    unsigned_b64 = swap_tx.get("swapTransaction")
    signed_b64 = sign_transaction(unsigned_b64)
    if not signed_b64:
        return ExecutionResult(ok=False, error="sign_failed", quote=quote)

    broadcast_result = await send_transaction(signed_b64)
    if not broadcast_result:
        return ExecutionResult(ok=False, error="broadcast_failed", quote=quote)

    await record_trade(session)
    return ExecutionResult(
        ok=True, signature=broadcast_result["signature"], quote=quote, usd_value=usd_value
    )
