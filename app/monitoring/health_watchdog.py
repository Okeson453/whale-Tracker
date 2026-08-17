"""Operational health monitoring — detects webhook silence and API error spikes.

Distinguishes "the bot is broken" from "there's just nothing to alert on."
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import yaml_settings

logger = logging.getLogger(__name__)


def _thresholds() -> dict[str, Any]:
    return yaml_settings.monitoring


def check_webhook_silence(last_webhook_at: datetime | None) -> str | None:
    """Return an alert message if no webhook has been received recently.

    Returns None if silence is within the acceptable threshold.
    """
    if last_webhook_at is None:
        return "No webhooks received since startup"

    threshold = _thresholds().get("webhook_silence_threshold_seconds", 300)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=threshold)
    if last_webhook_at < cutoff:
        delta = datetime.now(timezone.utc) - last_webhook_at
        return f"Webhook silence for {delta.total_seconds():.0f}s (threshold {threshold}s)"
    return None


def check_enrichment_error_rate(
    error_count: int, total_count: int
) -> str | None:
    """Return an alert message if the enrichment API error rate is too high.

    Returns None if the rate is acceptable or total_count is zero.
    """
    if total_count == 0:
        return None

    threshold = _thresholds().get("enrichment_error_rate_threshold", 0.2)
    rate = error_count / total_count
    if rate > threshold:
        return (
            f"Enrichment API error rate {rate:.1%} "
            f"({error_count}/{total_count}) exceeds threshold {threshold:.0%}"
        )
    return None


def check_system_health(
    last_webhook_at: datetime | None,
    enrichment_errors: int,
    enrichment_total: int,
) -> list[str]:
    """Run all health checks and return a list of active alerts.

    An empty list means the system appears healthy.
    """
    alerts: list[str] = []

    webhook_alert = check_webhook_silence(last_webhook_at)
    if webhook_alert:
        alerts.append(webhook_alert)

    enrichment_alert = check_enrichment_error_rate(enrichment_errors, enrichment_total)
    if enrichment_alert:
        alerts.append(enrichment_alert)

    if alerts:
        logger.warning("Health checks failed: %s", alerts)
    else:
        logger.debug("All health checks passed")

    return alerts
