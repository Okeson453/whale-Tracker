"""Narrative / social scoring.

A lightweight secondary filter — checks recent mention volume and
sentiment for a token before an alert goes out, alongside (not in place
of) the on-chain screening rules. Deliberately kept separate from
screening/rules_engine.py: this is an optional, low-confidence signal
and should never be able to silently change core screening behavior.

Failure handling matches the enrichment layer's convention: any API
failure returns None rather than fabricating a score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.config import yaml_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(5.0, connect=2.0)
_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class NarrativeSignal:
    token_mint: str
    mention_count: int
    sentiment_score: Decimal  # -100..100
    fetched_at: datetime


def _thresholds() -> dict[str, Any]:
    return yaml_settings.narrative


async def fetch_narrative_signal(
    token_mint: str, symbol: str | None = None
) -> NarrativeSignal | None:
    """Fetch mention volume + sentiment for a token from a social search API.

    The concrete provider is intentionally not hardcoded here — plug in
    whichever mention/sentiment API is configured (e.g. an X/Twitter
    search endpoint) via ``NARRATIVE_API_URL`` at the httpx call site.
    Returns None on any failure, timeout, or missing data — never a
    guessed or default score.
    """
    if not symbol:
        logger.debug("No symbol provided for %s — skipping narrative fetch", token_mint)
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Placeholder endpoint — wire to the configured provider.
            resp = await client.get(
                "https://api.example-social-search.invalid/v1/mentions",
                params={"q": symbol},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Narrative fetch failed for %s: %s", token_mint, exc)
        return None

    try:
        mention_count = int(data["mention_count"])
        sentiment = Decimal(str(data["sentiment_score"]))
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Narrative response malformed for %s: %s", token_mint, exc)
        return None

    return NarrativeSignal(
        token_mint=token_mint,
        mention_count=mention_count,
        sentiment_score=sentiment,
        fetched_at=datetime.now(timezone.utc),
    )


def passes_narrative_filter(signal: NarrativeSignal | None) -> tuple[bool, str | None]:
    """Apply the configured narrative thresholds to a fetched signal.

    Returns (passes, reason_if_not). A missing signal (API failure, no
    symbol) does not block an alert on its own — narrative is a secondary
    signal, not a gate — callers may choose to surface it as informational
    only when unavailable.
    """
    thresholds = _thresholds()
    min_mentions = thresholds.get("min_mention_count")
    min_sentiment = thresholds.get("min_sentiment_score")

    if signal is None:
        return True, "narrative_signal_unavailable"

    if min_mentions is not None and signal.mention_count < int(min_mentions):
        return False, f"mention_count_too_low ({signal.mention_count} < {min_mentions})"

    if min_sentiment is not None and signal.sentiment_score < Decimal(str(min_sentiment)):
        return (
            False,
            f"sentiment_too_low ({signal.sentiment_score} < {min_sentiment})",
        )

    return True, None
