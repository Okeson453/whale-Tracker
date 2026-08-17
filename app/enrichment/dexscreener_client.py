"""DexScreener API client — market cap, liquidity, volume for a token mint."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx

from app.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dexscreener.com/latest/dex/tokens"
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


def _pick_best_pair(pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Select the pair with the highest liquidityUSD."""
    if not pairs:
        return None
    best = max(
        pairs,
        key=lambda p: Decimal(p.get("liquidity", {}).get("usd", 0) or 0),
    )
    return best


async def get_token_data(token_mint: str) -> dict[str, Decimal | None] | None:
    """Fetch market data for *token_mint* from DexScreener.

    Returns a dict with keys ``market_cap``, ``liquidity_usd``, ``volume_24h``,
    or ``None`` on any failure.
    """
    url = f"{_BASE_URL}/{token_mint}"

    async def _fetch() -> dict:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    try:
        data = await retry_with_backoff(_fetch, op_name=f"dexscreener({token_mint})")
    except Exception as exc:
        logger.warning("DexScreener fetch failed for %s: %s", token_mint, exc)
        return None

    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        logger.warning("DexScreener returned no pairs for %s", token_mint)
        return None

    best = _pick_best_pair(pairs)
    if best is None:
        return None

    def _dec(key: str, sub: str | None = None) -> Decimal | None:
        try:
            val = best.get(key) if sub is None else best.get(key, {}).get(sub)
            if val is None:
                return None
            return Decimal(str(val))
        except Exception:
            return None

    return {
        "market_cap": _dec("marketCap"),
        "liquidity_usd": _dec("liquidity", "usd"),
        "volume_24h": _dec("volume", "h24"),
    }
