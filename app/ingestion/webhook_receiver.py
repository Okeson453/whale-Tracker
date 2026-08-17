"""FastAPI route for receiving Helius webhook payloads."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.confluence_detector import check_confluence
from app.analytics.wallet_performance import record_alert_outcome
from app.config import env, yaml_settings
from app.enrichment.enrichment_service import enrich_token
from app.execution.copy_trade_engine import (
    handle_whale_sell,
    maybe_auto_execute_buy,
    open_positions_wallet_addresses,
)
from app.ingestion.tx_parser import SwapEvent, parse_webhook_payload, parse_webhook_payload_sells
from app.ingestion.whale_registry import get_active_addresses, get_wallet_by_address
from app.notification.callback_handler import cache_alert
from app.notification.telegram_bot import send_alert
from app.screening.rules_engine import screen_event
from app.state.db import get_db_session
from app.state.models import Alert, SwapEvent as SwapEventModel
from app.utils.request_context import bind_request_id, new_request_id

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_webhook_secret(request: Request) -> None:
    """Validate Helius webhook Authorization header if secret is configured."""
    secret = env.helius_webhook_secret
    if not secret:
        return  # No secret configured — skip validation (dev mode)
    auth = request.headers.get("Authorization", "")
    if auth != secret:
        logger.warning("Invalid webhook secret from %s", request.client.host if request.client else "unknown")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret"
        )


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Accept a Helius Enhanced Transactions payload, parse buys, persist them,
    and trigger enrichment for each unique token mint.

    Binds a request id for the duration of this call so every log line
    from parse through alert can be traced back to this one webhook call,
    and echoes it back via X-Request-ID so Helius can correlate retries
    of the same delivery with our processing of it.
    """
    incoming_id = request.headers.get("X-Request-ID")
    request_id = incoming_id if incoming_id else new_request_id()
    bind_request_id(request_id)
    response.headers["X-Request-ID"] = request_id

    _verify_webhook_secret(request)

    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning("Malformed webhook JSON: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON"
        )

    tracked = await get_active_addresses(session)
    if not tracked:
        logger.debug("No tracked wallets; ignoring webhook")
        return {"processed": 0, "events": []}

    events = parse_webhook_payload(payload, tracked)
    logger.info(
        "Webhook parsed %d buy event(s) from %d tracked wallet(s)",
        len(events),
        len(tracked),
    )

    results: list[dict[str, Any]] = []
    enriched_mints: set[str] = set()

    for evt in events:
        # Duplicate suppression — skip if we've already seen this signature
        existing = await session.execute(
            select(SwapEventModel).where(SwapEventModel.signature == evt.signature)
        )
        if existing.scalar_one_or_none():
            logger.debug("Duplicate signature %s suppressed", evt.signature)
            continue

        wallet = await get_wallet_by_address(session, evt.wallet_address)
        if wallet is None:
            logger.warning("Wallet %s not found in DB; skipping event", evt.wallet_address)
            continue

        swap = SwapEventModel(
            wallet_id=wallet.id,
            token_mint=evt.token_mint,
            amount=evt.amount,
            signature=evt.signature,
            detected_at=evt.detected_at,
        )
        session.add(swap)
        await session.flush()

        # Enrich each unique token mint once per webhook batch
        profile = None
        if evt.token_mint not in enriched_mints:
            profile = await enrich_token(evt.token_mint, session)
            enriched_mints.add(evt.token_mint)

        # Session 7: screen + alert
        screened = False
        alert_id: str | None = None
        passed_screen: bool | None = None
        confluence_count: int | None = None
        if profile is not None:
            result = screen_event(evt, profile)

            if result.passed:
                # Record this buy against the multi-whale confluence window
                # and carry the resulting wallet count onto the alert so the
                # signal (">=2 tracked wallets in the same token") is visible
                # downstream instead of only living in confluence_detector's
                # own table. Confluence is informational here — it doesn't
                # gate the alert — but wallet_clustering-suspected wallets
                # could otherwise inflate it; that de-dup is a known gap,
                # see the accompanying notes.
                confluence = await check_confluence(session, evt.token_mint, evt.wallet_address)
                if confluence is not None:
                    confluence_count = confluence.alert_count

            alert = Alert(
                swap_event_id=swap.id,
                passed_screen=result.passed,
                skip_reasons=result.reasons if not result.passed else None,
                confluence_count=confluence_count,
            )
            session.add(alert)
            await session.flush()
            alert_id = alert.id
            screened = True
            passed_screen = result.passed

            # Update this wallet's scorecard with the outcome of this screen
            # so pass-rate-driven logic downstream (execution/whitelist.py's
            # auto-execute gate, execution/dynamic_sizing.py's position
            # sizing) has real data to read instead of always falling back
            # to "no scorecard" / minimum size.
            await record_alert_outcome(session, wallet.id, result.passed)

            if result.passed:
                # Auto-execution modes ("whitelist_auto" / "blind_auto") take
                # this alert straight to a buy and skip the human-approval
                # cache below entirely. approval_gate (default) leaves this
                # a no-op and falls through to the existing Telegram flow.
                auto_position = await maybe_auto_execute_buy(alert, evt, wallet, session)

                if auto_position is None:
                    sent = await send_alert(
                        env.telegram_bot_token,
                        env.telegram_chat_id,
                        evt,
                        profile,
                        result,
                        alert.id,
                        wallet.label,
                    )
                    if sent:
                        cache_alert(
                            alert.id,
                            {
                                "token_mint": evt.token_mint,
                                "amount_lamports": 1_000_000,
                                "slippage_bps": yaml_settings.execution.get(
                                    "max_slippage_bps", 500
                                ),
                            },
                        )

        results.append(
            {
                "wallet": evt.wallet_address,
                "token_mint": evt.token_mint,
                "amount": str(evt.amount),
                "signature": evt.signature,
                "enriched": profile is not None,
                "screened": screened,
                "alert_id": alert_id,
                "passed_screen": passed_screen,
                "confluence_count": confluence_count,
                "market_cap": str(profile.market_cap) if profile and profile.market_cap else None,
                "liquidity_usd": str(profile.liquidity_usd) if profile and profile.liquidity_usd else None,
            }
        )

    # Sell side of copy-trading: only scan for sells from wallets we
    # currently hold an open copied position against. Scoping to that
    # (usually small) address set, rather than every tracked whale, keeps
    # this from turning into an unbounded per-webhook table scan.
    sell_results: list[dict[str, Any]] = []
    positioned_addresses = await open_positions_wallet_addresses(session)
    if positioned_addresses:
        sell_events = parse_webhook_payload_sells(payload, positioned_addresses)
        for sell_evt in sell_events:
            wallet = await get_wallet_by_address(session, sell_evt.wallet_address)
            if wallet is None:
                continue
            position = await handle_whale_sell(sell_evt, wallet, session)
            sell_results.append(
                {
                    "wallet": sell_evt.wallet_address,
                    "token_mint": sell_evt.token_mint,
                    "signature": sell_evt.signature,
                    "position_closed": bool(position and position.status != "open"),
                }
            )

    await session.commit()
    return {"processed": len(results), "events": results, "sells": sell_results}
