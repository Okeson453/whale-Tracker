"""Build an unsigned Jupiter swap transaction from a quote."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import env

logger = logging.getLogger(__name__)

_JUPITER_SWAP_URL = "https://quote-api.jup.ag/v6/swap"
_TIMEOUT = httpx.Timeout(10.0, connect=3.0)


async def build_swap_tx(
    quote: dict[str, Any],
    user_public_key: str,
    wrap_unwrap_sol: bool = True,
    prioritization_fee_lamports: int | None = None,
) -> dict[str, Any] | None:
    """Request an unsigned swap transaction from Jupiter.

    Returns a dict with ``swapTransaction`` (base64) or ``None`` on failure.
    """
    payload: dict[str, Any] = {
        "quoteResponse": quote,
        "userPublicKey": user_public_key,
        "wrapAndUnwrapSol": wrap_unwrap_sol,
    }
    if prioritization_fee_lamports is not None:
        payload["prioritizationFeeLamports"] = prioritization_fee_lamports

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_JUPITER_SWAP_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            swap_tx = data.get("swapTransaction")
            if not swap_tx:
                logger.warning("Jupiter swap build returned no transaction")
                return None
            return data
    except Exception as exc:
        logger.warning("Jupiter swap build failed: %s", exc)
        return None
