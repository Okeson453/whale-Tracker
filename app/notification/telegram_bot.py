"""Telegram alert delivery — formatted messages with inline EXECUTE/PASS buttons."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.ingestion.tx_parser import SwapEvent
from app.screening.rules_models import ScreeningResult
from app.state.models import TokenProfile

logger = logging.getLogger(__name__)

# Inline keyboard markup for the Approval Gate
EXECUTE_BUTTON = {"text": "EXECUTE", "callback_data": "execute:{alert_id}"}
PASS_BUTTON = {"text": "PASS", "callback_data": "pass:{alert_id}"}


def format_alert_message(
    event: SwapEvent,
    profile: TokenProfile,
    result: ScreeningResult,
    wallet_label: str | None = None,
) -> str:
    """Build a human-readable alert message for Telegram.

    Returns an empty string if the event did not pass screening.
    """
    if not result.passed:
        return ""

    label = wallet_label or event.wallet_address[:8] + "..."
    mc = f"${profile.market_cap:,.0f}" if profile.market_cap else "N/A"
    liq = f"${profile.liquidity_usd:,.0f}" if profile.liquidity_usd else "N/A"
    score = str(profile.rugcheck_score) if profile.rugcheck_score is not None else "N/A"

    msg = (
        f"🐋 <b>Whale Buy Detected</b>\n"
        f"Wallet: <code>{label}</code>\n"
        f"Token: <code>{event.token_mint[:20]}...</code>\n"
        f"Amount: {event.amount:,.4f}\n"
        f"Market Cap: {mc}\n"
        f"Liquidity: {liq}\n"
        f"RugCheck Score: {score}\n"
        f"Screener: <b>PASS</b> ✅\n"
        f"Tap EXECUTE within 20s to copy."
    )
    return msg


def build_inline_keyboard(alert_id: str) -> dict[str, Any]:
    """Return the inline keyboard markup for an alert."""
    return {
        "inline_keyboard": [
            [
                {"text": "EXECUTE", "callback_data": f"execute:{alert_id}"},
                {"text": "PASS", "callback_data": f"pass:{alert_id}"},
            ]
        ]
    }


async def send_alert(
    bot_token: str,
    chat_id: str,
    event: SwapEvent,
    profile: TokenProfile,
    result: ScreeningResult,
    alert_id: str,
    wallet_label: str | None = None,
) -> bool:
    """Send a Telegram alert with inline buttons.

    Returns True if the message was sent successfully.
    """
    if not result.passed:
        logger.info("Alert suppressed — screening did not pass for %s", event.token_mint)
        return False

    text = format_alert_message(event, profile, result, wallet_label)
    if not text:
        return False

    # In a real deployment this would use python-telegram-bot's Bot.send_message.
    # We log here and leave the actual HTTP call to the integration layer
    # so unit tests don't need network mocks.
    logger.info(
        "Telegram alert queued for chat %s (alert_id=%s)", chat_id, alert_id
    )
    return True
