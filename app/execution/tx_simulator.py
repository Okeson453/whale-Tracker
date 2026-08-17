"""Transaction simulation pre-flight.

Sits between tx_builder.py and signer.py in the execution flow:

    tx_builder → simulate → [PASS] → signer → broadcaster
                  [FAIL] → log + abort, alert human with reason

Catches insufficient SOL for rent/gas, slippage exceeded, and program
errors (e.g. a frozen pool) via the RPC's simulateTransaction method
*before* a transaction is ever signed or broadcast — a failed simulation
costs nothing; a failed broadcast costs a transaction fee and, worse,
can leave a position in an ambiguous state.

This module never signs and never broadcasts. It only decides whether
it's safe to proceed to signer.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import env

logger = logging.getLogger(__name__)

_RPC_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


@dataclass(frozen=True)
class SimulationResult:
    ok: bool
    reason: str | None = None
    logs: list[str] | None = None
    units_consumed: int | None = None


async def simulate_transaction(unsigned_tx_base64: str) -> SimulationResult:
    """Simulate *unsigned_tx_base64* via the configured Solana RPC.

    Returns SimulationResult(ok=False, reason=...) on any RPC failure,
    program error, or malformed response — fail-closed, matching the
    convention used throughout enrichment and guardrails: an unverifiable
    outcome is treated as a failure, not a pass.
    """
    rpc_url = env.solana_rpc_url
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "simulateTransaction",
        "params": [
            unsigned_tx_base64,
            {
                "encoding": "base64",
                "sigVerify": False,
                "replaceRecentBlockhash": True,
                "commitment": "confirmed",
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=_RPC_TIMEOUT) as client:
            resp = await client.post(rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Transaction simulation RPC call failed: %s", exc)
        return SimulationResult(ok=False, reason=f"rpc_call_failed: {exc}")

    if "error" in data:
        logger.warning("Transaction simulation RPC error: %s", data["error"])
        return SimulationResult(ok=False, reason=f"rpc_error: {data['error']}")

    result = data.get("result", {}).get("value", {})
    err = result.get("err")
    logs = result.get("logs")
    units_consumed = result.get("unitsConsumed")

    if err is not None:
        reason = _classify_simulation_error(err, logs)
        logger.warning("Simulation predicts failure: %s", reason)
        return SimulationResult(ok=False, reason=reason, logs=logs)

    return SimulationResult(ok=True, logs=logs, units_consumed=units_consumed)


def _classify_simulation_error(err: Any, logs: list[str] | None) -> str:
    """Give a human-readable reason for a simulation error, using log
    text as a hint where the raw error code alone isn't self-explanatory.
    """
    log_text = " ".join(logs) if logs else ""

    if "insufficient lamports" in log_text.lower() or "insufficient funds" in log_text.lower():
        return "insufficient_sol_for_rent_or_gas"
    if "slippage" in log_text.lower():
        return "slippage_exceeded"
    if "frozen" in log_text.lower() or "paused" in log_text.lower():
        return "program_frozen_or_paused"

    return f"simulation_error: {err}"
