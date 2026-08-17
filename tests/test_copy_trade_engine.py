"""Tests for execution/copy_trade_engine.py — blind & whitelist auto-copy paths."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.execution.copy_trade_engine import (
    handle_whale_sell,
    maybe_auto_execute_buy,
    open_positions_wallet_addresses,
)
from app.execution.execution_service import ExecutionResult
from app.ingestion.tx_parser import SellEvent, SwapEvent
from app.state.models import Alert, Position, PositionStatus, SwapEvent as SwapEventModel, Wallet


@pytest.fixture
async def wallet(session):
    w = Wallet(address="WhaleCopy111111111111111111111111111111111", active=True)
    session.add(w)
    await session.commit()
    return w


@pytest.fixture
async def alert(session, wallet):
    swap = SwapEventModel(
        wallet_id=wallet.id,
        token_mint="TokenCopy11111111111111111111111111111111",
        amount=Decimal("1000"),
        signature="sig-buy-1",
    )
    session.add(swap)
    await session.flush()
    a = Alert(swap_event_id=swap.id, passed_screen=True)
    session.add(a)
    await session.commit()
    return a


def _swap_event(wallet_addr: str) -> SwapEvent:
    return SwapEvent(
        wallet_address=wallet_addr,
        token_mint="TokenCopy11111111111111111111111111111111",
        amount=Decimal("1000"),
        signature="sig-buy-1",
        detected_at=datetime.now(timezone.utc),
    )


class TestApprovalGateMode:
    async def test_no_op_when_mode_is_approval_gate(self, session, wallet, alert) -> None:
        with patch("app.execution.copy_trade_engine.yaml_settings") as mock_settings:
            mock_settings.execution = {"mode": "approval_gate"}
            position = await maybe_auto_execute_buy(alert, _swap_event(wallet.address), wallet, session)
        assert position is None


class TestBlindAutoMode:
    async def test_opens_position_on_successful_buy(self, session, wallet, alert) -> None:
        with patch("app.execution.copy_trade_engine.yaml_settings") as mock_settings, patch(
            "app.execution.copy_trade_engine.execute_buy_swap",
            new=AsyncMock(return_value=ExecutionResult(ok=True, signature="tx-buy-1")),
        ):
            mock_settings.execution = {"mode": "blind_auto", "max_slippage_bps": 500}
            position = await maybe_auto_execute_buy(alert, _swap_event(wallet.address), wallet, session)

        assert position is not None
        assert position.status == PositionStatus.open.value
        assert position.wallet_id == wallet.id
        assert position.amount_held == Decimal("1000")

    async def test_no_position_when_guardrails_block(self, session, wallet, alert) -> None:
        with patch("app.execution.copy_trade_engine.yaml_settings") as mock_settings, patch(
            "app.execution.copy_trade_engine.execute_buy_swap",
            new=AsyncMock(
                return_value=ExecutionResult(ok=False, error="guardrails_blocked", reasons=["slippage_too_high"])
            ),
        ):
            mock_settings.execution = {"mode": "blind_auto", "max_slippage_bps": 500}
            position = await maybe_auto_execute_buy(alert, _swap_event(wallet.address), wallet, session)

        assert position is None

    async def test_second_buy_tops_up_existing_position(self, session, wallet, alert) -> None:
        with patch("app.execution.copy_trade_engine.yaml_settings") as mock_settings, patch(
            "app.execution.copy_trade_engine.execute_buy_swap",
            new=AsyncMock(return_value=ExecutionResult(ok=True, signature="tx-buy-1")),
        ):
            mock_settings.execution = {"mode": "blind_auto", "max_slippage_bps": 500}
            first = await maybe_auto_execute_buy(alert, _swap_event(wallet.address), wallet, session)
            second = await maybe_auto_execute_buy(alert, _swap_event(wallet.address), wallet, session)

        assert first.id == second.id
        assert second.amount_held == Decimal("2000")


class TestWhitelistAutoMode:
    async def test_skips_non_whitelisted_wallet(self, session, wallet, alert) -> None:
        with patch("app.execution.copy_trade_engine.yaml_settings") as mock_settings, patch(
            "app.execution.copy_trade_engine.should_auto_execute",
            new=AsyncMock(return_value=(False, "no scorecard available")),
        ):
            mock_settings.execution = {"mode": "whitelist_auto", "max_slippage_bps": 500}
            position = await maybe_auto_execute_buy(alert, _swap_event(wallet.address), wallet, session)

        assert position is None


class TestHandleWhaleSell:
    async def test_no_open_position_is_a_no_op(self, session, wallet) -> None:
        sell = SellEvent(
            wallet_address=wallet.address,
            token_mint="TokenCopy11111111111111111111111111111111",
            amount=Decimal("1000"),
            signature="sig-sell-1",
            detected_at=datetime.now(timezone.utc),
        )
        result = await handle_whale_sell(sell, wallet, session)
        assert result is None

    async def test_closes_position_on_successful_sell(self, session, wallet, alert) -> None:
        with patch("app.execution.copy_trade_engine.yaml_settings") as mock_settings, patch(
            "app.execution.copy_trade_engine.execute_buy_swap",
            new=AsyncMock(return_value=ExecutionResult(ok=True, signature="tx-buy-1")),
        ):
            mock_settings.execution = {"mode": "blind_auto", "max_slippage_bps": 500}
            position = await maybe_auto_execute_buy(alert, _swap_event(wallet.address), wallet, session)
        assert position is not None

        sell = SellEvent(
            wallet_address=wallet.address,
            token_mint="TokenCopy11111111111111111111111111111111",
            amount=Decimal("1000"),
            signature="sig-sell-1",
            detected_at=datetime.now(timezone.utc),
        )
        with patch(
            "app.execution.copy_trade_engine.execute_sell_swap",
            new=AsyncMock(return_value=ExecutionResult(ok=True, signature="tx-sell-1")),
        ):
            closed = await handle_whale_sell(sell, wallet, session)

        assert closed.status == PositionStatus.closed.value
        assert closed.exit_trade_id is not None
        assert closed.closed_at is not None

    async def test_position_marked_exit_failed_when_sell_fails(self, session, wallet, alert) -> None:
        with patch("app.execution.copy_trade_engine.yaml_settings") as mock_settings, patch(
            "app.execution.copy_trade_engine.execute_buy_swap",
            new=AsyncMock(return_value=ExecutionResult(ok=True, signature="tx-buy-1")),
        ):
            mock_settings.execution = {"mode": "blind_auto", "max_slippage_bps": 500}
            position = await maybe_auto_execute_buy(alert, _swap_event(wallet.address), wallet, session)

        sell = SellEvent(
            wallet_address=wallet.address,
            token_mint="TokenCopy11111111111111111111111111111111",
            amount=Decimal("1000"),
            signature="sig-sell-1",
            detected_at=datetime.now(timezone.utc),
        )
        with patch(
            "app.execution.copy_trade_engine.execute_sell_swap",
            new=AsyncMock(return_value=ExecutionResult(ok=False, error="broadcast_failed")),
        ):
            result = await handle_whale_sell(sell, wallet, session)

        assert result.status == PositionStatus.exit_failed.value
        # Position stays "findable" as not-open so it doesn't get treated as
        # a healthy open position, but it's also not silently lost — a human
        # needs to look at exit_failed positions.
        reopened = await handle_whale_sell(sell, wallet, session)
        assert reopened is None  # no longer "open", so a second sell event is a no-op


class TestOpenPositionsWalletAddresses:
    async def test_returns_addresses_with_open_positions(self, session, wallet, alert) -> None:
        with patch("app.execution.copy_trade_engine.yaml_settings") as mock_settings, patch(
            "app.execution.copy_trade_engine.execute_buy_swap",
            new=AsyncMock(return_value=ExecutionResult(ok=True, signature="tx-buy-1")),
        ):
            mock_settings.execution = {"mode": "blind_auto", "max_slippage_bps": 500}
            await maybe_auto_execute_buy(alert, _swap_event(wallet.address), wallet, session)

        addresses = await open_positions_wallet_addresses(session)
        assert wallet.address in addresses

    async def test_empty_when_no_open_positions(self, session, wallet) -> None:
        addresses = await open_positions_wallet_addresses(session)
        assert addresses == []
