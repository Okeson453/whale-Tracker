"""Orchestrate Jupiter, DexScreener, and RugCheck into a single TokenProfile.

On any API failure the entire profile is discarded (returns ``None``);
we never alert with partial or unverified data.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.enrichment.dexscreener_client import get_token_data
from app.enrichment.jupiter_client import get_price
from app.enrichment.rugcheck_client import get_report
from app.state.models import TokenProfile

logger = logging.getLogger(__name__)


async def enrich_token(
    token_mint: str, session: AsyncSession
) -> TokenProfile | None:
    """Fetch enrichment data for *token_mint* from all three APIs.

    Returns a fully populated ``TokenProfile`` or ``None`` if any
    upstream call fails.
    """
    # Run all three fetches concurrently
    price_task = get_price(token_mint)
    dex_task = get_token_data(token_mint)
    rug_task = get_report(token_mint)

    price, dex_data, rug_data = await asyncio.gather(
        price_task, dex_task, rug_task, return_exceptions=True
    )

    # Treat any exception as a failure → return None
    for result in (price, dex_data, rug_data):
        if isinstance(result, Exception):
            logger.warning(
                "Enrichment failed for %s due to exception: %s", token_mint, result
            )
            return None

    # If any individual client returned None, treat as failure
    if price is None or dex_data is None or rug_data is None:
        logger.warning(
            "Partial enrichment for %s — price=%s dex=%s rug=%s; dropping event",
            token_mint,
            price is not None,
            dex_data is not None,
            rug_data is not None,
        )
        return None

    from sqlalchemy import select

    existing = await session.execute(
        select(TokenProfile).where(TokenProfile.token_mint == token_mint)
    )
    profile = existing.scalar_one_or_none()
    if profile is None:
        profile = TokenProfile(token_mint=token_mint)
        session.add(profile)

    profile.market_cap = dex_data.get("market_cap")
    profile.liquidity_usd = dex_data.get("liquidity_usd")
    profile.volume_24h = dex_data.get("volume_24h")
    profile.price_usd = price
    profile.rugcheck_score = rug_data.get("score")
    profile.risks = rug_data.get("risks")
    profile.fetched_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(profile)
    logger.info("Enriched token %s (MC=%s, Liq=%s)", token_mint, profile.market_cap, profile.liquidity_usd)
    return profile
