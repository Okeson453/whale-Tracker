"""Broadcast signed transactions to Solana RPC and confirm landing."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import env

logger = logging.getLogger(__name__)

_RPC_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


async def send_transaction(signed_tx_base64: str) -> dict[str, Any] | None:
    """Broadcast a signed transaction via the configured Solana RPC.

    Returns the RPC response dict or ``None`` on failure.
    """
    rpc_url = env.solana_rpc_url
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendTransaction",
        "params": [
            signed_tx_base64,
            {
                "encoding": "base64",
                "skipPreflight": False,
                "preflightCommitment": "confirmed",
                "maxRetries": 3,
            },
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=_RPC_TIMEOUT) as client:
            resp = await client.post(rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("RPC broadcast failed: %s", exc)
        return None

    if "error" in data:
        logger.error("RPC error: %s", data["error"])
        return None

    signature = data.get("result")
    if not signature:
        logger.error("RPC returned no signature")
        return None

    logger.info("Transaction broadcasted: %s", signature)
    return {"signature": signature, "status": "submitted"}


async def confirm_transaction(signature: str, max_wait_seconds: int = 30) -> bool:
    """Poll the RPC until the transaction is confirmed or timeout.

    Returns True if confirmed, False otherwise.
    """
    rpc_url = env.solana_rpc_url
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignatureStatuses",
        "params": [[signature], {"searchTransactionHistory": True}],
    }

    deadline = time.monotonic() + max_wait_seconds
    async with httpx.AsyncClient(timeout=_RPC_TIMEOUT) as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.post(rpc_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("Confirmation poll failed: %s", exc)
                await asyncio.sleep(2)
                continue

            statuses = data.get("result", {}).get("value", [])
            if statuses and statuses[0]:
                confirmation_status = statuses[0].get("confirmationStatus")
                if confirmation_status in ("confirmed", "finalized"):
                    logger.info("Transaction %s confirmed (%s)", signature, confirmation_status)
                    return True
                if statuses[0].get("err"):
                    logger.error("Transaction %s failed: %s", signature, statuses[0]["err"])
                    return False

            await asyncio.sleep(2)

    logger.warning("Transaction %s confirmation timed out", signature)
    return False
