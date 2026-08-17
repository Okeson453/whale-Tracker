"""Jupiter Price API client — returns USD price per token mint."""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from app.config import env
from app.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

_BASE_URL = "https://price.jup.ag/v4"
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


async def get_price(token_mint: str) -> Decimal | None:
    """Fetch the current USD price for *token_mint*.

    Retries transient failures with exponential backoff before falling
    back to the existing fail-closed behavior. Returns ``None`` on
    exhausted retries, an HTTP error status, or an unparseable response.
    """
    url = f"{_BASE_URL}/price"
    params = {"ids": token_mint}

    async def _fetch() -> dict:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    try:
        data = await retry_with_backoff(_fetch, op_name=f"jupiter_price({token_mint})")
    except Exception as exc:
        logger.warning("Jupiter price fetch failed for %s: %s", token_mint, exc)
        return None

    try:
        price_data = data.get("data", {}).get(token_mint, {})
        raw_price = price_data.get("price")
        if raw_price is None:
            logger.warning("Jupiter returned no price for %s", token_mint)
            return None
        return Decimal(str(raw_price))
    except Exception as exc:
        logger.warning("Jupiter price parse failed for %s: %s", token_mint, exc)
        return None
