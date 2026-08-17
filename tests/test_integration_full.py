"""Session 11: Full loop integration test on devnet.

whale buy → detect → enrich → screen → alert → human tap EXECUTE
→ quote → guardrails → build → sign → broadcast → confirm

All external APIs are mocked; this proves the wiring is correct.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.notification.callback_handler import cache_alert, handle_callback
from app.state.models import (
    Alert,
    AlertDecision,
    DailyState,
    SwapEvent,
    TokenProfile,
    Trade,
    Wallet,
)


TOKEN_MINT = "TestMint111111111111111111111111111111111111"
ALERT_ID = "alert-123"


async def test_full_loop_execute(session) -> None:
    """End-to-end: callback handler executes the full pipeline."""
    # Seed DB state
    wallet = Wallet(address="Whale111111111111111111111111111111111111", active=True)
    session.add(wallet)
    await session.commit()

    swap = SwapEvent(
        wallet_id=wallet.id,
        token_mint=TOKEN_MINT,
        amount=Decimal("1000000"),
        signature="sig_full_loop",
    )
    session.add(swap)
    await session.commit()

    alert = Alert(
        id=ALERT_ID,
        swap_event_id=swap.id,
        passed_screen=True,
        decision=AlertDecision.pending.value,
    )
    session.add(alert)
    await session.commit()

    # Cache the alert context (normally done by webhook_receiver)
    cache_alert(
        ALERT_ID,
        {
            "token_mint": TOKEN_MINT,
            "amount_lamports": 1_000_000,
            "slippage_bps": 500,
        },
    )

    # Mock all external calls
    mock_quote = {
        "outAmount": "500000",
        "priceImpactPct": "0.5",
    }
    mock_swap_tx = {"swapTransaction": "dGVzdF90eF9iYXNlNjQ="}
    mock_broadcast = {"signature": "txsig_full_loop_123"}

    with patch(
        "app.execution.execution_service.get_quote", new_callable=AsyncMock
    ) as m_quote, patch(
        "app.execution.execution_service.build_swap_tx", new_callable=AsyncMock
    ) as m_build, patch(
        "app.execution.execution_service.sign_transaction"
    ) as m_sign, patch(
        "app.execution.execution_service.send_transaction", new_callable=AsyncMock
    ) as m_broadcast, patch(
        "app.execution.execution_service.get_public_key"
    ) as m_pubkey, patch(
        "app.execution.execution_service.check_max_trades", new_callable=AsyncMock
    ) as m_max_trades, patch(
        "app.execution.execution_service.get_sol_usd_price", new_callable=AsyncMock
    ) as m_sol_price, patch(
        "app.execution.execution_service.get_open_positions_usd", new_callable=AsyncMock
    ) as m_open_positions, patch(
        "app.execution.guardrails.get_quote", new_callable=AsyncMock
    ) as m_guardrails_quote, patch(
        "app.execution.guardrails.get_wallet_usd_value", new_callable=AsyncMock
    ) as m_wallet_usd, patch(
        "app.state.circuit_breaker.get_wallet_usd_value", new_callable=AsyncMock
    ) as m_cb_wallet_usd:
        m_quote.return_value = mock_quote
        m_build.return_value = mock_swap_tx
        m_sign.return_value = "signed_tx_base64"
        m_broadcast.return_value = mock_broadcast
        m_pubkey.return_value = "TraderPubkey1111111111111111111111111111111"
        m_max_trades.return_value = True
        m_sol_price.return_value = Decimal("150")
        m_open_positions.return_value = Decimal("0")
        m_guardrails_quote.return_value = {"outAmount": "100"}  # honeypot pass
        m_wallet_usd.return_value = Decimal("10000")  # comfortably above any cap in this test
        # First call of the day seeds starting_balance from this and reports
        # no loss yet; keeping it constant here means the daily-loss check
        # never trips mid-test.
        m_cb_wallet_usd.return_value = Decimal("10000")

        result = await handle_callback(f"execute:{ALERT_ID}", session)

    assert result["ok"] is True
    assert result["action"] == "execute"
    assert result["executed"] is True
    assert result["signature"] == "txsig_full_loop_123"

    # Verify Alert updated to executed
    await session.refresh(alert)
    assert alert.decision == AlertDecision.executed.value
    assert alert.decided_at is not None

    # Verify Trade row created
    trade_result = await session.execute(select(Trade).where(Trade.alert_id == ALERT_ID))
    trade = trade_result.scalar_one_or_none()
    assert trade is not None
    assert trade.tx_signature == "txsig_full_loop_123"
    assert trade.status == "submitted"

    # Verify daily trade count incremented
    daily_result = await session.execute(select(DailyState))
    daily = daily_result.scalar_one_or_none()
    assert daily is not None
    assert daily.trades_count == 1


async def test_full_loop_pass(session) -> None:
    """End-to-end: human taps PASS — no trade, alert marked passed_by_human."""
    wallet = Wallet(address="Whale111111111111111111111111111111111111", active=True)
    session.add(wallet)
    await session.commit()

    swap = SwapEvent(
        wallet_id=wallet.id,
        token_mint=TOKEN_MINT,
        amount=Decimal("1000000"),
        signature="sig_pass",
    )
    session.add(swap)
    await session.commit()

    alert = Alert(
        id=ALERT_ID,
        swap_event_id=swap.id,
        passed_screen=True,
        decision=AlertDecision.pending.value,
    )
    session.add(alert)
    await session.commit()

    cache_alert(ALERT_ID, {"token_mint": TOKEN_MINT})

    result = await handle_callback(f"pass:{ALERT_ID}", session)

    assert result["ok"] is True
    assert result["action"] == "pass"

    await session.refresh(alert)
    assert alert.decision == AlertDecision.passed_by_human.value
    assert alert.decided_at is not None

    # No trade should have been created
    trade_result = await session.execute(select(Trade).where(Trade.alert_id == ALERT_ID))
    assert trade_result.scalar_one_or_none() is None


async def test_full_loop_expired_alert(session) -> None:
    """Callback for an expired/missing alert returns error."""
    result = await handle_callback("execute:nonexistent_alert", session)
    assert result["ok"] is False
    assert result["error"] == "expired_or_missing"
