"""Ops alerting — separate notification channel for operational issues.

Sends to Discord webhook or a secondary Telegram chat so trade alerts
and ops alerts don't get mixed together.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import env

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


async def send_ops_alert(message: str) -> bool:
    """Send an operational alert to the configured ops channel.

    Prefers Discord webhook; falls back to Telegram if Discord is not configured.
    Returns True if the message was dispatched successfully.
    """
    discord_url = env.discord_webhook_url
    if discord_url:
        return await _send_discord(discord_url, message)

    telegram_token = env.telegram_bot_token
    telegram_chat = env.telegram_chat_id
    if telegram_token and telegram_chat:
        return await _send_telegram(telegram_token, telegram_chat, message)

    logger.warning("No ops alerting channel configured — message dropped: %s", message)
    return False


async def _send_discord(webhook_url: str, message: str) -> bool:
    payload = {"content": f"🚨 **Ops Alert**\n{message}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Discord ops alert failed: %s", exc)
        return False


async def _send_telegram(token: str, chat_id: str, message: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": f"🚨 Ops Alert\n{message}",
        "parse_mode": "HTML",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Telegram ops alert failed: %s", exc)
        return False
