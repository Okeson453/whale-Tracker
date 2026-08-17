"""On-chain SPL token metadata — currently just decimals lookup.

Needed to convert a UI-decimal token amount (what Helius's tokenTransfers
and this project's Position.amount_held both store) into the raw atomic
integer Jupiter's quote API requires for the *input* side of a sell.
"""

from __future__ import annotations

import logging

import httpx

from app.config import env

logger = logging.getLogger(__name__)

_RPC_TIMEOUT = httpx.Timeout(10.0, connect=3.0)

# Short-lived process-local cache — a mint's decimals never change, so
# there's no correctness reason to re-fetch it every sell.
_decimals_cache: dict[str, int] = {}


async def get_token_decimals(token_mint: str) -> int | None:
    """Return the number of decimals for *token_mint* via getTokenSupply,
    or None if the RPC call fails or the mint is malformed. Callers must
    fail closed on None — do not assume 6 or 9 decimals as a fallback,
    guessing wrong here silently over- or under-sells by orders of
    magnitude.
    """
    if token_mint in _decimals_cache:
        return _decimals_cache[token_mint]

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenSupply",
        "params": [token_mint],
    }
    try:
        async with httpx.AsyncClient(timeout=_RPC_TIMEOUT) as client:
            resp = await client.post(env.solana_rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("getTokenSupply RPC call failed for %s: %s", token_mint, exc)
        return None

    if "error" in data:
        logger.warning("getTokenSupply RPC error for %s: %s", token_mint, data["error"])
        return None

    decimals = data.get("result", {}).get("value", {}).get("decimals")
    if decimals is None:
        logger.warning("getTokenSupply returned no decimals for %s", token_mint)
        return None

    _decimals_cache[token_mint] = int(decimals)
    return int(decimals)
