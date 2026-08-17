"""Sample Helius Enhanced Transactions webhook payloads for tests."""

from __future__ import annotations

TRACKED_WALLET = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
TOKEN_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC devnet stand-in


def buy_payload() -> dict:
    """A Helius tx where the tracked wallet receives tokens (buy)."""
    return {
        "signature": "5Jv...buy",
        "type": "SWAP",
        "timestamp": 1715000000,
        "accountData": [
            {"account": TRACKED_WALLET, "nativeBalanceChange": -1000000000},
        ],
        "tokenTransfers": [
            {
                "fromUserAccount": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                "toUserAccount": TRACKED_WALLET,
                "mint": TOKEN_MINT,
                "tokenAmount": 1250.5,
            }
        ],
        "nativeTransfers": [
            {
                "fromUserAccount": TRACKED_WALLET,
                "toUserAccount": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                "amount": 1000000000,
            }
        ],
    }


def sell_payload() -> dict:
    """A Helius tx where the tracked wallet sends tokens (sell)."""
    return {
        "signature": "5Jv...sell",
        "type": "SWAP",
        "timestamp": 1715000001,
        "accountData": [
            {"account": TRACKED_WALLET, "nativeBalanceChange": 950000000},
        ],
        "tokenTransfers": [
            {
                "fromUserAccount": TRACKED_WALLET,
                "toUserAccount": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                "mint": TOKEN_MINT,
                "tokenAmount": 1250.5,
            }
        ],
        "nativeTransfers": [
            {
                "fromUserAccount": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                "toUserAccount": TRACKED_WALLET,
                "amount": 950000000,
            }
        ],
    }


def non_swap_payload() -> dict:
    """A plain SOL transfer with no token movement."""
    return {
        "signature": "5Jv...transfer",
        "type": "TRANSFER",
        "timestamp": 1715000002,
        "accountData": [
            {"account": TRACKED_WALLET, "nativeBalanceChange": -500000000},
        ],
        "tokenTransfers": [],
        "nativeTransfers": [
            {
                "fromUserAccount": TRACKED_WALLET,
                "toUserAccount": "SomeOtherWallet111111111111111111111111111111",
                "amount": 500000000,
            }
        ],
    }


def multi_tx_payload() -> list[dict]:
    """A batch of two txs: one buy, one sell."""
    return [buy_payload(), sell_payload()]
