"""SOL/USD pricing and on-chain wallet balance — real feeds, no placeholders.

Used anywhere a USD position size needs converting to lamports, and by
guardrails.check_position_cap to size the cap against actual wallet value
instead of a nominal placeholder balance.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from app.config import env
from app.enrichment.jupiter_client import get_price
from app.execution.quote_service import WSOL_MINT
from app.execution.signer import get_public_key

logger = logging.getLogger(__name__)

_RPC_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
_LAMPORTS_PER_SOL = Decimal(10**9)


async def get_sol_usd_price() -> Decimal | None:
    """Current SOL/USD price via Jupiter's price API. None on failure —
    callers must fail closed (no trade sizing on a missing price), not
    fall back to a guessed number.
    """
    price = await get_price(WSOL_MINT)
    if price is None:
        logger.warning("SOL/USD price unavailable")
    return price


async def get_wallet_sol_balance() -> Decimal | None:
    """SOL balance of the trading wallet (derived from the configured
    signing key), via the same RPC used for broadcasting. Returns None if
    there's no signing key configured yet or the RPC call fails — callers
    must treat that as "cannot verify capacity", not "wallet is empty".
    """
    pubkey = get_public_key()
    if not pubkey:
        return None

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [pubkey],
    }
    try:
        async with httpx.AsyncClient(timeout=_RPC_TIMEOUT) as client:
            resp = await client.post(env.solana_rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("getBalance RPC call failed: %s", exc)
        return None

    if "error" in data:
        logger.warning("getBalance RPC error: %s", data["error"])
        return None

    lamports = data.get("result", {}).get("value")
    if lamports is None:
        logger.warning("getBalance RPC returned no value")
        return None

    return Decimal(lamports) / _LAMPORTS_PER_SOL


async def get_wallet_usd_value() -> Decimal | None:
    """Trading wallet's SOL balance converted to USD. None if either the
    balance or the price is unavailable — never silently substitutes one
    missing input with a guess.
    """
    balance, price = await get_wallet_sol_balance(), await get_sol_usd_price()
    if balance is None or price is None:
        return None
    return balance * price


def usd_to_lamports(usd_amount: Decimal, sol_usd_price: Decimal) -> int:
    """Convert a USD trade size to lamports at the given SOL/USD price."""
    if sol_usd_price <= 0:
        raise ValueError("sol_usd_price must be positive")
    sol_amount = usd_amount / sol_usd_price
    return int(sol_amount * _LAMPORTS_PER_SOL)
