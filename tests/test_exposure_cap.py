"""Tests for execution/exposure_cap.py."""

from __future__ import annotations

from decimal import Decimal

from app.execution.exposure_cap import check_correlated_exposure, get_open_exposure_for_trait
from app.state.models import Alert, SwapEvent, Trade, TradeStatus, Wallet


async def _seed_trade(
    session, wallet_address: str, token_mint: str, signature: str, usd_value: Decimal, status: str
) -> Trade:
    wallet = Wallet(address=wallet_address, active=True)
    session.add(wallet)
    await session.flush()

    event = SwapEvent(
        wallet_id=wallet.id,
        token_mint=token_mint,
        amount=Decimal("100"),
        signature=signature,
    )
    session.add(event)
    await session.flush()

    alert = Alert(swap_event_id=event.id, passed_screen=True)
    session.add(alert)
    await session.flush()

    trade = Trade(alert_id=alert.id, usd_value=usd_value, status=status)
    session.add(trade)
    await session.commit()
    return trade


async def test_get_open_exposure_sums_matching_trait(session) -> None:
    await _seed_trade(
        session, "W1", "TOKEN_A", "sig1", Decimal("100"), TradeStatus.confirmed.value
    )
    await _seed_trade(
        session, "W2", "TOKEN_B", "sig2", Decimal("150"), TradeStatus.submitted.value
    )
    # TOKEN_A and TOKEN_B share deployer "DEV1"; a third unrelated token doesn't
    await _seed_trade(
        session, "W3", "TOKEN_C", "sig3", Decimal("999"), TradeStatus.confirmed.value
    )

    trait_lookup = {"TOKEN_A": "DEV1", "TOKEN_B": "DEV1", "TOKEN_C": "DEV2"}
    total = await get_open_exposure_for_trait(session, "DEV1", trait_lookup)
    assert total == Decimal("250")


async def test_get_open_exposure_excludes_failed_trades(session) -> None:
    await _seed_trade(
        session, "W1", "TOKEN_A", "sig1", Decimal("100"), TradeStatus.failed.value
    )
    trait_lookup = {"TOKEN_A": "DEV1"}
    total = await get_open_exposure_for_trait(session, "DEV1", trait_lookup)
    assert total == Decimal("0")


async def test_check_correlated_exposure_no_trait_passes(session) -> None:
    reason = await check_correlated_exposure(session, None, Decimal("500"), {})
    assert reason is None


async def test_check_correlated_exposure_under_cap_passes(session) -> None:
    await _seed_trade(
        session, "W1", "TOKEN_A", "sig1", Decimal("50"), TradeStatus.confirmed.value
    )
    trait_lookup = {"TOKEN_A": "DEV1"}
    # cap is 300 (default config) — 50 existing + 100 new = 150, under cap
    reason = await check_correlated_exposure(session, "DEV1", Decimal("100"), trait_lookup)
    assert reason is None


async def test_check_correlated_exposure_over_cap_blocks(session) -> None:
    await _seed_trade(
        session, "W1", "TOKEN_A", "sig1", Decimal("250"), TradeStatus.confirmed.value
    )
    trait_lookup = {"TOKEN_A": "DEV1"}
    # cap is 300 (default config) — 250 existing + 100 new = 350, over cap
    reason = await check_correlated_exposure(session, "DEV1", Decimal("100"), trait_lookup)
    assert reason is not None
    assert "correlated_exposure_exceeded" in reason
