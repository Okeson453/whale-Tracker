"""RugCheck API client — risk score and flagged risks for a token mint."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.rugcheck.xyz/v1"
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


async def get_report(token_mint: str) -> dict[str, Any] | None:
    """Fetch the RugCheck report for *token_mint*.

    Returns a dict with keys ``score`` (int) and ``risks`` (list[str]),
    or ``None`` on any failure.
    """
    url = f"{_BASE_URL}/tokens/{token_mint}/report"

    async def _fetch() -> dict:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    try:
        data = await retry_with_backoff(_fetch, op_name=f"rugcheck({token_mint})")
    except Exception as exc:
        logger.warning("RugCheck fetch failed for %s: %s", token_mint, exc)
        return None

    try:
        score = data.get("score")
        risks = data.get("risks", [])
        if not isinstance(risks, list):
            risks = []
        risk_names = [r.get("name", r.get("description", str(r))) for r in risks if isinstance(r, dict)]
        return {
            "score": int(score) if score is not None else None,
            "risks": risk_names,
        }
    except Exception as exc:
        logger.warning("RugCheck parse failed for %s: %s", token_mint, exc)
        return None
