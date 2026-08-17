"""Tests for analytics/narrative_scoring.py."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.analytics.narrative_scoring import (
    NarrativeSignal,
    fetch_narrative_signal,
    passes_narrative_filter,
)


async def test_fetch_narrative_signal_no_symbol_returns_none() -> None:
    signal = await fetch_narrative_signal("TOKENMINT", symbol=None)
    assert signal is None


async def test_fetch_narrative_signal_api_failure_returns_none() -> None:
    # No network access in test env / invalid host — must fail closed to None.
    signal = await fetch_narrative_signal("TOKENMINT", symbol="DOGE2")
    assert signal is None


def test_passes_narrative_filter_none_signal_does_not_block() -> None:
    passed, reason = passes_narrative_filter(None)
    assert passed is True
    assert reason == "narrative_signal_unavailable"


def test_passes_narrative_filter_meets_thresholds() -> None:
    signal = NarrativeSignal(
        token_mint="T1",
        mention_count=50,
        sentiment_score=Decimal("30"),
        fetched_at=datetime.now(timezone.utc),
    )
    passed, reason = passes_narrative_filter(signal)
    assert passed is True
    assert reason is None


def test_passes_narrative_filter_low_mentions_fails() -> None:
    signal = NarrativeSignal(
        token_mint="T1",
        mention_count=1,
        sentiment_score=Decimal("30"),
        fetched_at=datetime.now(timezone.utc),
    )
    passed, reason = passes_narrative_filter(signal)
    assert passed is False
    assert "mention_count_too_low" in reason


def test_passes_narrative_filter_low_sentiment_fails() -> None:
    signal = NarrativeSignal(
        token_mint="T1",
        mention_count=50,
        sentiment_score=Decimal("-10"),
        fetched_at=datetime.now(timezone.utc),
    )
    passed, reason = passes_narrative_filter(signal)
    assert passed is False
    assert "sentiment_too_low" in reason
