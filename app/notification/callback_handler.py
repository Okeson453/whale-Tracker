"""Handle Telegram inline button presses.

Session 10: wired to real execution (quote → guardrails → sign → broadcast).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.execution_service import execute_buy_swap
from app.state.models import Alert, AlertDecision, Trade, TradeStatus

logger = logging.getLogger(__name__)

# In-memory cache for pending alerts awaiting human decision.
# Maps alert_id → dict with swap_event, token_profile, etc.
_pending_alerts: dict[str, dict[str, Any]] = {}


def cache_alert(alert_id: str, context: dict[str, Any]) -> None:
    """Store alert context so the callback handler can look it up."""
    _pending_alerts[alert_id] = context
    logger.debug("Cached alert %s for callback", alert_id)


def get_cached_alert(alert_id: str) -> dict[str, Any] | None:
    """Retrieve cached alert context by ID."""
    return _pending_alerts.get(alert_id)


def clear_alert(alert_id: str) -> None:
    """Remove an alert from the cache."""
    _pending_alerts.pop(alert_id, None)


async def handle_callback(
    callback_data: str, session: AsyncSession
) -> dict[str, Any]:
    """Process a Telegram callback query.

    Expected callback_data formats:
      - "execute:{alert_id}"
      - "pass:{alert_id}"

    Returns a dict describing the action taken.
    """
    if ":" not in callback_data:
        logger.warning("Malformed callback data: %s", callback_data)
        return {"ok": False, "error": "malformed_callback"}

    action, alert_id = callback_data.split(":", 1)
    context = get_cached_alert(alert_id)

    if context is None:
        logger.warning("Alert %s not found or expired", alert_id)
        return {"ok": False, "error": "expired_or_missing", "alert_id": alert_id}

    if action == "pass":
        logger.info("Human tapped PASS for alert %s", alert_id)
        alert = await session.get(Alert, alert_id)
        if alert:
            alert.decision = AlertDecision.passed_by_human.value
            alert.decided_at = datetime.now(timezone.utc)
            await session.commit()
        clear_alert(alert_id)
        return {"ok": True, "action": "pass", "alert_id": alert_id}

    if action == "execute":
        logger.info("Human tapped EXECUTE for alert %s", alert_id)
        return await _execute_trade(alert_id, context, session)

    logger.warning("Unknown callback action: %s", action)
    return {"ok": False, "error": "unknown_action", "alert_id": alert_id}


async def _execute_trade(
    alert_id: str, context: dict[str, Any], session: AsyncSession
) -> dict[str, Any]:
    """Run the full execution pipeline for an approved alert."""
    token_mint = context["token_mint"]
    amount_lamports = context.get("amount_lamports", 1_000_000)  # 0.001 SOL default
    slippage_bps = context.get("slippage_bps", 500)

    result = await execute_buy_swap(token_mint, amount_lamports, slippage_bps, session)
    if not result.ok:
        logger.warning("Execution failed for alert %s — %s", alert_id, result.error)
        return {
            "ok": False,
            "error": result.error,
            "reasons": result.reasons,
            "alert_id": alert_id,
        }

    alert = await session.get(Alert, alert_id)
    if alert:
        alert.decision = AlertDecision.executed.value
        alert.decided_at = datetime.now(timezone.utc)

    trade = Trade(
        alert_id=alert_id,
        tx_signature=result.signature,
        usd_value=result.usd_value,
        status=TradeStatus.submitted.value,
    )
    session.add(trade)
    await session.commit()

    clear_alert(alert_id)
    logger.info("Trade executed for alert %s — tx %s", alert_id, result.signature)
    return {
        "ok": True,
        "action": "execute",
        "alert_id": alert_id,
        "executed": True,
        "signature": result.signature,
    }
