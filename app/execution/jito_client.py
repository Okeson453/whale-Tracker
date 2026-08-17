"""Jito bundle submission for MEV-protected transaction landing.

Routes buys through Jito's block-engine to reduce sandwich-bot risk.
Devnet/mainnet compatible; returns None on any API failure.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import env

logger = logging.getLogger(__name__)

# Jito block-engine endpoints
_JITO_MAINNET = "https://mainnet.block-engine.jito.wtf/api/v1"
_JITO_DEVNET = "https://devnet.block-engine.jito.wtf/api/v1"
_TIMEOUT = httpx.Timeout(10.0, connect=3.0)


def _base_url() -> str:
    """Select Jito endpoint based on the configured RPC URL."""
    rpc = env.solana_rpc_url
    if "devnet" in rpc:
        return _JITO_DEVNET
    return _JITO_MAINNET


async def get_tip_account() -> str | None:
    """Fetch a Jito tip account to include in the bundle.

    Returns the tip account address or None on failure.
    """
    url = f"{_base_url()}/bundles/tip_account"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            accounts = data.get("accounts", [])
            if accounts:
                return accounts[0]
    except Exception as exc:
        logger.warning("Jito tip account fetch failed: %s", exc)
    return None


async def submit_bundle(
    transactions: list[str],
    tip_lamports: int = 10000,
) -> dict[str, Any] | None:
    """Submit a list of base64-encoded transactions as a Jito bundle.

    *transactions* should include the swap tx plus an optional tip tx.
    Returns the bundle result dict or None on failure.
    """
    url = f"{_base_url()}/bundles"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendBundle",
        "params": [transactions],
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Jito bundle submission failed: %s", exc)
        return None

    if "error" in data:
        logger.error("Jito bundle error: %s", data["error"])
        return None

    bundle_id = data.get("result")
    if not bundle_id:
        logger.error("Jito returned no bundle ID")
        return None

    logger.info("Jito bundle submitted: %s", bundle_id)
    return {"bundle_id": bundle_id, "status": "submitted"}
