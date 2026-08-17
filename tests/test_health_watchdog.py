"""Tests for monitoring/health_watchdog.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.monitoring.health_watchdog import (
    check_enrichment_error_rate,
    check_system_health,
    check_webhook_silence,
)


class TestCheckWebhookSilence:
    def test_no_webhooks(self) -> None:
        result = check_webhook_silence(None)
        assert result is not None
        assert "No webhooks" in result

    def test_recent_webhook(self) -> None:
        recent = datetime.now(timezone.utc) - timedelta(seconds=10)
        assert check_webhook_silence(recent) is None

    def test_silence_exceeded(self) -> None:
        old = datetime.now(timezone.utc) - timedelta(seconds=400)
        result = check_webhook_silence(old)
        assert result is not None
        assert "silence" in result.lower()


class TestCheckEnrichmentErrorRate:
    def test_no_calls(self) -> None:
        assert check_enrichment_error_rate(0, 0) is None

    def test_within_threshold(self) -> None:
        assert check_enrichment_error_rate(1, 10) is None

    def test_exceeds_threshold(self) -> None:
        result = check_enrichment_error_rate(5, 10)
        assert result is not None
        assert "error rate" in result


class TestCheckSystemHealth:
    def test_all_healthy(self) -> None:
        recent = datetime.now(timezone.utc) - timedelta(seconds=10)
        alerts = check_system_health(recent, 1, 10)
        assert alerts == []

    def test_multiple_issues(self) -> None:
        old = datetime.now(timezone.utc) - timedelta(seconds=400)
        alerts = check_system_health(old, 5, 10)
        assert len(alerts) == 2
