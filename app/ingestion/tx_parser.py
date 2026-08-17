"""Parse Helius Enhanced Transactions webhook payload into SwapEvents.

Only emits an event when a tracked wallet's token balance increased (a buy).
Sells and non-swap transactions are silently ignored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SwapEvent:
    wallet_address: str
    token_mint: str
    amount: Decimal
    signature: str
    detected_at: datetime


@dataclass(frozen=True)
class SellEvent:
    """A tracked wallet sending a token out — the mirror image of SwapEvent.

    Only emitted by ``parse_sell_transaction`` / ``parse_webhook_payload_sells``,
    which are called with a *narrow* address list (wallets we currently hold
    a copied position against), not every tracked whale — see the caller in
    ``webhook_receiver.py`` for why that scoping matters.
    """

    wallet_address: str
    token_mint: str
    amount: Decimal
    signature: str
    detected_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_token_transfers(
    tx: dict[str, Any], tracked_address: str
) -> list[dict[str, Any]]:
    """Return token transfers where the tracked wallet is the recipient."""
    transfers = tx.get("tokenTransfers", [])
    matched: list[dict[str, Any]] = []
    for t in transfers:
        to_addr = t.get("toUserAccount", "")
        if to_addr and to_addr.lower() == tracked_address.lower():
            matched.append(t)
    return matched


def _extract_sol_spent(
    tx: dict[str, Any], tracked_address: str
) -> Decimal | None:
    """Return SOL amount sent by the tracked wallet (for buy-size estimation)."""
    native = tx.get("nativeTransfers", [])
    total = Decimal("0")
    found = False
    for n in native:
        from_addr = n.get("fromUserAccount", "")
        if from_addr and from_addr.lower() == tracked_address.lower():
            total += Decimal(str(n.get("amount", 0))) / Decimal(1e9)
            found = True
    return total if found else None


def _is_sell(tx: dict[str, Any], tracked_address: str) -> bool:
    """Check if the tracked wallet sent any tokens in this tx (sell indicator)."""
    transfers = tx.get("tokenTransfers", [])
    for t in transfers:
        from_addr = t.get("fromUserAccount", "")
        if from_addr and from_addr.lower() == tracked_address.lower():
            return True
    return False


def parse_transaction(
    tx: dict[str, Any], tracked_address: str
) -> SwapEvent | None:
    """Normalize a single Helius tx into a SwapEvent if it is a tracked-wallet buy.

    Returns None for sells, non-swaps, or malformed payloads.
    """
    signature = tx.get("signature")
    if not signature:
        logger.debug("Skipping tx with no signature")
        return None

    tx_type = tx.get("type", "").upper()
    if tx_type not in ("SWAP", "UNKNOWN"):
        # Helius sometimes tags complex DEX interactions as UNKNOWN;
        # we still inspect tokenTransfers rather than hard-reject.
        pass

    # If the wallet sent tokens, treat as sell → ignore
    if _is_sell(tx, tracked_address):
        logger.debug("Ignoring sell tx %s for %s", signature, tracked_address)
        return None

    incoming = _extract_token_transfers(tx, tracked_address)
    if not incoming:
        logger.debug("No incoming token transfers in tx %s for %s", signature, tracked_address)
        return None

    # Take the first incoming token transfer as the primary buy.
    # Multi-token swaps are edge-case; we alert on the first received token.
    primary = incoming[0]
    token_mint = primary.get("mint")
    raw_amount = primary.get("tokenAmount")
    if not token_mint or raw_amount is None:
        logger.debug("Incomplete token transfer in tx %s", signature)
        return None

    try:
        amount = Decimal(str(raw_amount))
    except Exception:
        logger.warning("Unparseable token amount %r in tx %s", raw_amount, signature)
        return None

    return SwapEvent(
        wallet_address=tracked_address,
        token_mint=token_mint,
        amount=amount,
        signature=signature,
        detected_at=_now(),
    )


def parse_webhook_payload(
    payload: dict[str, Any], tracked_addresses: set[str]
) -> list[SwapEvent]:
    """Parse a full Helius webhook payload (list of txs) into SwapEvents.

    The payload may be either a list of transactions or a dict with a
    ``data`` / ``transactions`` key containing the list.
    """
    events: list[SwapEvent] = []

    txs: list[dict[str, Any]] = []
    if isinstance(payload, list):
        txs = payload
    elif isinstance(payload, dict):
        txs = payload.get("data", payload.get("transactions", []))
        if not isinstance(txs, list):
            txs = [txs] if isinstance(txs, dict) else []
    else:
        logger.warning("Unexpected webhook payload type: %s", type(payload).__name__)
        return events

    for tx in txs:
        # Determine which tracked wallet this tx concerns.
        # Helius accountData includes all accounts; we scan for a match.
        account_data = tx.get("accountData", [])
        involved = set()
        for acc in account_data:
            addr = acc.get("account", "")
            if addr and addr.lower() in {a.lower() for a in tracked_addresses}:
                involved.add(addr)

        # Also check tokenTransfers for addresses not in accountData
        for t in tx.get("tokenTransfers", []):
            for key in ("fromUserAccount", "toUserAccount"):
                addr = t.get(key, "")
                if addr and addr.lower() in {a.lower() for a in tracked_addresses}:
                    involved.add(addr)

        for addr in involved:
            event = parse_transaction(tx, addr)
            if event:
                events.append(event)

    return events

def parse_sell_transaction(
    tx: dict[str, Any], tracked_address: str
) -> SellEvent | None:
    """Normalize a single Helius tx into a SellEvent if it is a tracked-wallet sell.

    Mirror image of ``parse_transaction``: only fires when the tracked
    wallet sent tokens out. Multi-token sells take the first outgoing
    transfer, same simplification as the buy side.
    """
    signature = tx.get("signature")
    if not signature:
        return None

    outgoing = [
        t
        for t in tx.get("tokenTransfers", [])
        if (t.get("fromUserAccount", "") or "").lower() == tracked_address.lower()
    ]
    if not outgoing:
        return None

    primary = outgoing[0]
    token_mint = primary.get("mint")
    raw_amount = primary.get("tokenAmount")
    if not token_mint or raw_amount is None:
        logger.debug("Incomplete outgoing token transfer in tx %s", signature)
        return None

    try:
        amount = Decimal(str(raw_amount))
    except Exception:
        logger.warning("Unparseable sell amount %r in tx %s", raw_amount, signature)
        return None

    return SellEvent(
        wallet_address=tracked_address,
        token_mint=token_mint,
        amount=amount,
        signature=signature,
        detected_at=_now(),
    )


def parse_webhook_payload_sells(
    payload: Any, tracked_addresses: list[str]
) -> list[SellEvent]:
    """Extract sell events for a (deliberately narrow) set of addresses.

    Callers should pass only wallets we currently hold a copied position
    against — see ``webhook_receiver.py``. Structurally identical to
    ``parse_webhook_payload`` otherwise.
    """
    events: list[SellEvent] = []
    if not tracked_addresses:
        return events

    txs: list[dict[str, Any]] = []
    if isinstance(payload, list):
        txs = payload
    elif isinstance(payload, dict):
        txs = payload.get("data", payload.get("transactions", []))
        if not isinstance(txs, list):
            txs = [txs] if isinstance(txs, dict) else []
    else:
        return events

    lowered = {a.lower() for a in tracked_addresses}
    for tx in txs:
        involved = set()
        for t in tx.get("tokenTransfers", []):
            addr = t.get("fromUserAccount", "")
            if addr and addr.lower() in lowered:
                involved.add(addr)
        for addr in involved:
            event = parse_sell_transaction(tx, addr)
            if event:
                events.append(event)

    return events
