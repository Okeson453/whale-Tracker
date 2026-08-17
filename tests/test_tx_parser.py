"""Tests for tx_parser — prove buys are detected and sells are ignored."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ingestion.tx_parser import parse_transaction, parse_webhook_payload
from tests.fixtures.webhook_payloads import (
    TRACKED_WALLET,
    buy_payload,
    multi_tx_payload,
    non_swap_payload,
    sell_payload,
)


class TestParseTransaction:
    def test_buy_detected(self) -> None:
        tx = buy_payload()
        event = parse_transaction(tx, TRACKED_WALLET)
        assert event is not None
        assert event.wallet_address == TRACKED_WALLET
        assert event.token_mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert event.amount == Decimal("1250.5")
        assert event.signature == "5Jv...buy"

    def test_sell_ignored(self) -> None:
        tx = sell_payload()
        event = parse_transaction(tx, TRACKED_WALLET)
        assert event is None

    def test_non_swap_ignored(self) -> None:
        tx = non_swap_payload()
        event = parse_transaction(tx, TRACKED_WALLET)
        assert event is None

    def test_untracked_wallet_returns_none(self) -> None:
        tx = buy_payload()
        event = parse_transaction(tx, "UntrackedWallet1111111111111111111111111111")
        assert event is None


class TestParseWebhookPayload:
    def test_list_payload_buy_only(self) -> None:
        payload = [buy_payload()]
        events = parse_webhook_payload(payload, {TRACKED_WALLET})
        assert len(events) == 1
        assert events[0].signature == "5Jv...buy"

    def test_list_payload_sell_ignored(self) -> None:
        payload = [sell_payload()]
        events = parse_webhook_payload(payload, {TRACKED_WALLET})
        assert len(events) == 0

    def test_mixed_batch(self) -> None:
        payload = multi_tx_payload()
        events = parse_webhook_payload(payload, {TRACKED_WALLET})
        assert len(events) == 1
        assert events[0].signature == "5Jv...buy"

    def test_dict_wrapper(self) -> None:
        payload = {"data": [buy_payload()]}
        events = parse_webhook_payload(payload, {TRACKED_WALLET})
        assert len(events) == 1

    def test_no_tracked_wallets(self) -> None:
        payload = [buy_payload()]
        events = parse_webhook_payload(payload, set())
        assert len(events) == 0

    def test_empty_payload(self) -> None:
        events = parse_webhook_payload([], {TRACKED_WALLET})
        assert len(events) == 0
