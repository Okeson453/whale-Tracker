"""Correlated-exposure cap.

Blocks a new position if it would push total open exposure to tokens
sharing a common trait — e.g. the same deployer wallet, the same launch
platform, or the same wallet cluster (see analytics/wallet_clustering.py)
— above a configured threshold. This guards against the failure mode
where several "different" tokens or wallets are actually one underlying
actor, and a string of guardrail-passing trades ends up concentrated in
a single point of failure.

The shared trait is supplied by the caller as an opaque string key
(e.g. a deployer address) — this module has no opinion on how that key
is derived, only on capping exposure once it's known.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import yaml_settings
from app.state.models import Alert, SwapEvent, Trade, TradeStatus

logger = logging.getLogger(__name__)


def _max_correlated_exposure_usd() -> Decimal:
    raw = yaml_settings.exposure_cap.get("max_correlated_exposure_usd", 300)
    return Decimal(str(raw))


async def get_open_exposure_for_trait(
    session: AsyncSession, shared_trait_key: str, trait_lookup: dict[str, str]
) -> Decimal:
    """Sum USD value of confirmed/submitted trades whose token maps to
    *shared_trait_key* via *trait_lookup* (token_mint -> trait key).

    *trait_lookup* is supplied by the caller (e.g. built from a deployer-
    address or wallet-cluster index) rather than queried here, keeping
    this module free of assumptions about where the trait comes from.
    """
    result = await session.execute(
        select(Trade, SwapEvent.token_mint)
        .join(Alert, Trade.alert_id == Alert.id)
        .join(SwapEvent, Alert.swap_event_id == SwapEvent.id)
        .where(Trade.status.in_([TradeStatus.submitted.value, TradeStatus.confirmed.value]))
    )

    total = Decimal("0")
    for trade, token_mint in result.all():
        if trait_lookup.get(token_mint) == shared_trait_key and trade.usd_value:
            total += trade.usd_value
    return total


async def check_correlated_exposure(
    session: AsyncSession,
    shared_trait_key: str | None,
    new_trade_usd: Decimal,
    trait_lookup: dict[str, str],
) -> str | None:
    """Return a guardrail skip reason if adding this trade would exceed
    the correlated-exposure cap for *shared_trait_key*.

    A None or empty shared_trait_key means no correlation trait is known
    for this token — the check passes (fail-open only for the *absence*
    of a trait, not for exposure once a trait is known).
    """
    if not shared_trait_key:
        return None

    cap = _max_correlated_exposure_usd()
    current = await get_open_exposure_for_trait(session, shared_trait_key, trait_lookup)
    projected = current + new_trade_usd

    if projected > cap:
        reason = (
            f"correlated_exposure_exceeded (trait={shared_trait_key}, "
            f"current=${current}, new=${new_trade_usd}, cap=${cap})"
        )
        logger.warning(reason)
        return reason

    return None
