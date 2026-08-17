"""Copy-trade orchestration: whale buy → (maybe) auto-buy → hold → whale sell → auto-sell.

Execution mode is read from ``settings.yaml: execution.mode`` on every
call (not cached), so flipping the mode in config takes effect on the
next webhook without a restart:

  - "approval_gate" (default) — existing behavior. Nothing here fires;
    the alert is cached for a human to tap Execute in Telegram.
  - "whitelist_auto"  — auto-buy, but only for wallets that have earned
    it via ``execution/whitelist.py`` (win-rate + min observed alerts).
    This is the safer automated mode and the one the whitelist module
    was already built for.
  - "blind_auto" — auto-buy on *every* tracked wallet's passed-screen
    alert, no performance gate. This is what "blind copy-trading" means:
    every screened buy from every wallet you're tracking gets mirrored
    unconditionally. There's no wallet-quality filter standing between a
    bad whale and your capital in this mode — the only backstops left
    are the existing guardrails (slippage cap, honeypot check) and the
    circuit breaker (daily loss halt, max trades/day). Both position
    sizing (``dynamic_sizing``) and per-wallet caps still apply.

Selling mirrors buying: once a position is open, the next detected sell
from the *same* wallet on the *same* token triggers an exit for the full
held amount, regardless of which mode opened the position — if you're
willing to auto-enter behind a whale you're also on the hook to auto-exit
behind them, otherwise a bot would sit holding a bag the whale already
dropped.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.wallet_performance import get_wallet_scorecard
from app.config import yaml_settings
from app.execution.dynamic_sizing import calculate_position_size
from app.execution.execution_service import execute_buy_swap, execute_sell_swap
from app.execution.pricing import get_sol_usd_price, usd_to_lamports
from app.execution.token_metadata import get_token_decimals
from app.execution.whitelist import should_auto_execute
from app.ingestion.tx_parser import SellEvent, SwapEvent
from app.state.models import (
    Alert,
    AlertDecision,
    Position,
    PositionStatus,
    Trade,
    TradeStatus,
    Wallet,
)

logger = logging.getLogger(__name__)


def _execution_mode() -> str:
    return yaml_settings.execution.get("mode", "approval_gate")


def _sell_slippage_bps() -> int:
    return int(yaml_settings.execution.get("sell_slippage_bps", 500))


async def _size_buy_in_lamports(
    session: AsyncSession, wallet_id: str
) -> tuple[int | None, str | None]:
    """Real USD sizing via dynamic_sizing.py (wallet-scorecard-aware),
    converted to lamports at the live SOL/USD price. Returns
    (amount_lamports, error) — error is set (and amount None) if the
    price feed is unavailable, rather than falling back to a guessed
    clip size.
    """
    scorecard = await get_wallet_scorecard(session, wallet_id)
    usd_size = calculate_position_size(scorecard)

    sol_price = await get_sol_usd_price()
    if sol_price is None:
        return None, "sol_price_unavailable"

    return usd_to_lamports(usd_size, sol_price), None


async def maybe_auto_execute_buy(
    alert: Alert,
    event: SwapEvent,
    wallet: Wallet,
    session: AsyncSession,
) -> Position | None:
    """Called for every alert that passed screening. Returns the opened
    Position if this alert triggered an automatic buy, else None (meaning
    it was left for the approval-gate / Telegram path, as before).
    """
    mode = _execution_mode()
    if mode == "approval_gate":
        return None

    if mode == "whitelist_auto":
        allowed, reason = await should_auto_execute(session, wallet.id)
        if not allowed:
            logger.info(
                "Wallet %s not auto-execute eligible (%s) — leaving for approval gate",
                wallet.address,
                reason,
            )
            return None
    elif mode != "blind_auto":
        logger.warning("Unknown execution.mode %r — treating as approval_gate", mode)
        return None

    amount_lamports, size_err = await _size_buy_in_lamports(session, wallet.id)
    if size_err:
        logger.warning(
            "Auto-buy blocked for wallet=%s token=%s — %s", wallet.address, event.token_mint, size_err
        )
        return None

    result = await execute_buy_swap(
        event.token_mint, amount_lamports, yaml_settings.execution.get("max_slippage_bps", 500), session
    )

    alert.decision = AlertDecision.executed.value if result.ok else alert.decision
    if not result.ok:
        logger.warning(
            "Auto-buy blocked for wallet=%s token=%s mode=%s — %s (%s)",
            wallet.address,
            event.token_mint,
            mode,
            result.error,
            result.reasons,
        )
        return None

    trade = Trade(
        alert_id=alert.id,
        tx_signature=result.signature,
        usd_value=result.usd_value,
        status=TradeStatus.submitted.value,
    )
    session.add(trade)
    await session.flush()

    position = await _open_or_top_up_position(
        session, wallet.id, event.token_mint, event.amount, trade.id, result.usd_value
    )
    await session.commit()

    logger.info(
        "AUTO-BUY executed — mode=%s wallet=%s token=%s tx=%s position=%s",
        mode,
        wallet.address,
        event.token_mint,
        result.signature,
        position.id,
    )
    return position


async def _open_or_top_up_position(
    session: AsyncSession,
    wallet_id: str,
    token_mint: str,
    amount_delta: Decimal,
    trade_id: str,
    usd_value_delta: Decimal | None,
) -> Position:
    existing = await _get_open_position(session, wallet_id, token_mint)
    if existing:
        existing.amount_held += amount_delta
        if usd_value_delta is not None:
            existing.entry_usd_value = (existing.entry_usd_value or Decimal("0")) + usd_value_delta
        return existing

    position = Position(
        wallet_id=wallet_id,
        token_mint=token_mint,
        entry_trade_id=trade_id,
        amount_held=amount_delta,
        entry_usd_value=usd_value_delta,
        status=PositionStatus.open.value,
    )
    session.add(position)
    await session.flush()
    return position


async def _get_open_position(
    session: AsyncSession, wallet_id: str, token_mint: str
) -> Position | None:
    result = await session.execute(
        select(Position).where(
            Position.wallet_id == wallet_id,
            Position.token_mint == token_mint,
            Position.status == PositionStatus.open.value,
        )
    )
    return result.scalar_one_or_none()


async def open_positions_wallet_addresses(session: AsyncSession) -> list[str]:
    """Addresses of wallets we currently hold at least one open copied
    position against — used to scope sell-side webhook scanning so we're
    not parsing every tracked whale's sells, only the ones that matter.
    """
    result = await session.execute(
        select(Wallet.address)
        .join(Position, Position.wallet_id == Wallet.id)
        .where(Position.status == PositionStatus.open.value)
        .distinct()
    )
    return [row[0] for row in result.all()]


async def handle_whale_sell(
    event: SellEvent, wallet: Wallet, session: AsyncSession
) -> Position | None:
    """A tracked whale we hold a copied position against just sold. Mirror
    it: sell our full held amount of that token, close the position.

    Fires regardless of ``execution.mode`` — the mode only gates whether we
    auto-*enter*; once we're already holding something because of a whale,
    exiting when they exit is the whole point of copy-trading and isn't
    itself an extra risk decision.
    """
    position = await _get_open_position(session, wallet.id, event.token_mint)
    if position is None:
        # No copied position for this wallet/token — nothing to mirror.
        return None

    # position.amount_held is stored in UI-decimal units (whatever Helius's
    # tokenTransfers.tokenAmount gave us at buy time — same convention
    # tx_parser.py uses for buys). Jupiter's quote API needs a raw atomic
    # integer, so convert using the mint's real decimals rather than
    # assuming any particular value.
    decimals = await get_token_decimals(event.token_mint)
    if decimals is None:
        logger.error(
            "AUTO-SELL BLOCKED — could not fetch decimals for %s (position=%s). "
            "Refusing to guess a decimals value and risk an order-of-magnitude "
            "sizing error; position left open for manual handling.",
            event.token_mint,
            position.id,
        )
        position.status = PositionStatus.exit_failed.value
        await session.commit()
        return position

    amount_atoms = int(position.amount_held * (Decimal(10) ** decimals))
    if amount_atoms <= 0:
        logger.warning(
            "Position %s has non-positive amount_held (%s) — marking closed without a sell tx",
            position.id,
            position.amount_held,
        )
        position.status = PositionStatus.closed.value
        await session.commit()
        return position

    result = await execute_sell_swap(
        event.token_mint, amount_atoms, _sell_slippage_bps(), session
    )

    if not result.ok:
        logger.error(
            "AUTO-SELL FAILED — wallet=%s token=%s position=%s error=%s reasons=%s. "
            "Position left open; a stuck exit needs a human to look at it.",
            wallet.address,
            event.token_mint,
            position.id,
            result.error,
            result.reasons,
        )
        position.status = PositionStatus.exit_failed.value
        await session.commit()
        return position

    exit_trade = Trade(
        alert_id=None,  # exits aren't triggered by a screening alert; traceable via Position.exit_trade_id instead
        tx_signature=result.signature,
        status=TradeStatus.submitted.value,
    )
    session.add(exit_trade)
    await session.flush()

    position.exit_trade_id = exit_trade.id
    position.status = PositionStatus.closed.value
    from datetime import datetime, timezone

    position.closed_at = datetime.now(timezone.utc)
    await session.commit()

    logger.info(
        "AUTO-SELL executed — wallet=%s token=%s position=%s tx=%s",
        wallet.address,
        event.token_mint,
        position.id,
        result.signature,
    )
    return position
