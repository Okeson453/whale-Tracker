"""Transaction signing — isolated module for key-safety scrutiny.

Loads the trading keypair from env and signs base64-encoded Solana
transactions (as returned by Jupiter's /swap endpoint — a v0
VersionedTransaction) using solders. Every function here fails closed:
on any error signing returns None rather than an unsigned or malformed
transaction, and the caller (execution_service.py) already treats a
None here as a hard stop.

The private key never leaves this process and is never logged. Do not
add logging of ``raw``, ``key_bytes``, or the decoded keypair anywhere
in this file.
"""

from __future__ import annotations

import base64
import logging
from functools import lru_cache

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from app.config import env

logger = logging.getLogger(__name__)


def _decode_private_key(raw: str) -> bytes | None:
    """Decode TRADER_PRIVATE_KEY, trying base58 first (the Solana CLI /
    Phantom export format), then base64, then raw hex. Returns the
    32- or 64-byte key material, or None if none of the encodings fit.
    """
    if not raw:
        return None

    try:
        import base58

        decoded = base58.b58decode(raw)
        if len(decoded) in (32, 64):
            return decoded
    except Exception:
        pass

    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) in (32, 64):
            return decoded
    except Exception:
        pass

    try:
        decoded = bytes.fromhex(raw)
        if len(decoded) in (32, 64):
            return decoded
    except Exception:
        pass

    logger.error(
        "TRADER_PRIVATE_KEY set but not decodable as base58/base64/hex, "
        "or not a 32- or 64-byte key"
    )
    return None


@lru_cache(maxsize=1)
def _load_keypair() -> Keypair | None:
    """Load and cache the trading Keypair for this process's lifetime.

    Cached deliberately: re-decoding the private key on every trade is
    unnecessary handling of secret bytes. The cache is keyed on nothing
    (maxsize=1, no args) because there is exactly one trading key per
    process — if that ever needs to change (multiple trading wallets),
    this needs a real keystore, not a bigger cache.
    """
    raw = env.trader_private_key
    if not raw:
        logger.warning("TRADER_PRIVATE_KEY not set — signing unavailable")
        return None

    key_bytes = _decode_private_key(raw)
    if key_bytes is None:
        return None

    try:
        if len(key_bytes) == 64:
            return Keypair.from_bytes(key_bytes)
        # 32-byte seed only (no embedded public key) — derive from seed.
        return Keypair.from_seed(key_bytes)
    except Exception as exc:
        logger.error("Failed to construct Keypair from TRADER_PRIVATE_KEY: %s", exc)
        return None


def get_public_key() -> str | None:
    """Return the base58-encoded public key of the trading wallet."""
    keypair = _load_keypair()
    if keypair is None:
        return None
    return str(keypair.pubkey())


def clear_keypair_cache() -> None:
    """Drop the cached Keypair so a changed TRADER_PRIVATE_KEY (or a test
    fixture) is picked up on the next call. Not used in normal operation —
    the process only ever needs one key for its lifetime.
    """
    _load_keypair.cache_clear()


def sign_transaction(unsigned_tx_base64: str) -> str | None:
    """Sign a base64-encoded v0 VersionedTransaction and return it re-encoded.

    Returns None on any failure — a missing key, an undecodable payload,
    a transaction the loaded key isn't authorized to sign, or a
    serialization error. Callers must treat None as "do not broadcast",
    never as "broadcast unsigned".
    """
    keypair = _load_keypair()
    if keypair is None:
        logger.error("Cannot sign — no trading keypair available")
        return None

    if not unsigned_tx_base64:
        logger.error("Cannot sign — empty transaction payload")
        return None

    try:
        raw = base64.b64decode(unsigned_tx_base64, validate=True)
    except Exception as exc:
        logger.error("Cannot sign — undecodable base64 transaction: %s", exc)
        return None

    try:
        unsigned_tx = VersionedTransaction.from_bytes(raw)
    except Exception as exc:
        logger.error("Cannot sign — malformed VersionedTransaction: %s", exc)
        return None

    try:
        message_bytes = bytes(unsigned_tx.message)
        signature = keypair.sign_message(message_bytes)
        signed_tx = VersionedTransaction.populate(unsigned_tx.message, [signature])
    except Exception as exc:
        logger.error("Cannot sign — signing operation failed: %s", exc)
        return None

    try:
        return base64.b64encode(bytes(signed_tx)).decode("ascii")
    except Exception as exc:
        logger.error("Cannot sign — re-serialization failed: %s", exc)
        return None
