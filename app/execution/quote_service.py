"""Jupiter Swap API v6 quote service — devnet/testnet only."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx

from app.config import env

logger = logging.getLogger(__name__)

_JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
_TIMEOUT = httpx.Timeout(10.0, connect=3.0)

# Wrapped SOL on devnet / mainnet
WSOL_MINT = "So11111111111111111111111111111111111111112"


async def get_quote(
    output_mint: str,
    amount_lamports: int,
    slippage_bps: int = 500,
    input_mint: str | None = None,
) -> dict[str, Any] | None:
    """Fetch a Jupiter swap quote.

    Defaults to buying *output_mint* with SOL. Set *input_mint* to
    quote in the reverse direction (e.g. for honeypot sell-checks).

    Returns the raw quote JSON or ``None`` on failure.
    """
    params = {
        "inputMint": input_mint or WSOL_MINT,
        "outputMint": output_mint,
        "amount": str(amount_lamports),
        "slippageBps": str(slippage_bps),
        "onlyDirectRoutes": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_JUPITER_QUOTE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("data") and not data.get("outAmount"):
                logger.warning("Jupiter returned empty quote for %s", output_mint)
                return None
            return data
    except Exception as exc:
        logger.warning("Jupiter quote failed for %s: %s", output_mint, exc)
        return None
