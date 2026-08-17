"""Multi-whale confluence detection.

Raises alert confidence when 2+ tracked wallets buy the same token
within a configurable time window.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.analytics_models import ConfluenceEventDataclass
from app.config import yaml_settings
from app.state.models import ConfluenceEvent

logger = logging.getLogger(__name__)


def _window_seconds() -> int:
    return yaml_settings.analytics.get("confluence_window_seconds", 300)


async def check_confluence(
    session: AsyncSession,
    token_mint: str,
    wallet_address: str,
    window_seconds: int | None = None,
) -> ConfluenceEventDataclass | None:
    """Check if another tracked wallet bought *token_mint* recently.

    If a confluence event exists and the new wallet is not already
    recorded, updates the event. Returns the current confluence state
    or None if this is the first buy in the window.
    """
    window = window_seconds or _window_seconds()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window)

    result = await session.execute(
        select(ConfluenceEvent)
        .where(ConfluenceEvent.token_mint == token_mint)
        .where(ConfluenceEvent.last_seen_at >= cutoff)
        .order_by(ConfluenceEvent.first_seen_at.desc())
    )
    existing = result.scalars().first()

    if existing is None:
        # First buy in window — create a new confluence event
        event = ConfluenceEvent(
            token_mint=token_mint,
            wallet_addresses=[wallet_address],
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        logger.info(
            "Confluence seed for %s by %s", token_mint, wallet_address
        )
        return ConfluenceEventDataclass(
            token_mint=event.token_mint,
            wallet_addresses=event.wallet_addresses,
            first_seen_at=event.first_seen_at,
            last_seen_at=event.last_seen_at,
            alert_count=event.alert_count,
        )

    # Existing event — add wallet if new
    if wallet_address not in existing.wallet_addresses:
        existing.wallet_addresses = existing.wallet_addresses + [wallet_address]
        existing.alert_count += 1
        existing.last_seen_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(existing)
        logger.info(
            "Confluence BOOST for %s — wallets: %s",
            token_mint,
            existing.wallet_addresses,
        )

    return ConfluenceEventDataclass(
        token_mint=existing.token_mint,
        wallet_addresses=existing.wallet_addresses,
        first_seen_at=existing.first_seen_at,
        last_seen_at=existing.last_seen_at,
        alert_count=existing.alert_count,
    )


async def get_recent_confluence(
    session: AsyncSession,
    token_mint: str,
    min_wallets: int = 2,
    window_seconds: int | None = None,
) -> ConfluenceEventDataclass | None:
    """Return a confluence event for *token_mint* only if it meets
    the minimum wallet threshold within the time window.
    """
    window = window_seconds or _window_seconds()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window)

    result = await session.execute(
        select(ConfluenceEvent)
        .where(ConfluenceEvent.token_mint == token_mint)
        .where(ConfluenceEvent.last_seen_at >= cutoff)
        .where(ConfluenceEvent.alert_count >= min_wallets)
        .order_by(ConfluenceEvent.first_seen_at.desc())
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    return ConfluenceEventDataclass(
        token_mint=row.token_mint,
        wallet_addresses=row.wallet_addresses,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        alert_count=row.alert_count,
    )
