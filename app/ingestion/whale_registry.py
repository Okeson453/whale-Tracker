"""CRUD for tracked whale wallets backed by the async DB layer."""

from __future__ import annotations

import logging
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.state.models import Wallet

logger = logging.getLogger(__name__)


async def add_wallet(
    session: AsyncSession, address: str, label: str | None = None
) -> Wallet:
    """Register a new whale wallet. Raises on duplicate address."""
    existing = await session.execute(
        select(Wallet).where(Wallet.address == address)
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Wallet already tracked: {address}")

    wallet = Wallet(address=address, label=label, active=True)
    session.add(wallet)
    await session.commit()
    await session.refresh(wallet)
    logger.info("Added wallet %s (%s)", address, label or "no label")
    return wallet


async def remove_wallet(session: AsyncSession, address: str) -> bool:
    """Remove a wallet by address. Returns True if found and deleted."""
    result = await session.execute(
        select(Wallet).where(Wallet.address == address)
    )
    wallet = result.scalar_one_or_none()
    if not wallet:
        return False
    await session.delete(wallet)
    await session.commit()
    logger.info("Removed wallet %s", address)
    return True


async def list_wallets(
    session: AsyncSession, active_only: bool = False
) -> Sequence[Wallet]:
    """List tracked wallets, optionally filtering to active ones."""
    stmt = select(Wallet)
    if active_only:
        stmt = stmt.where(Wallet.active.is_(True))
    result = await session.execute(stmt)
    return result.scalars().all()


async def toggle_wallet(session: AsyncSession, address: str, active: bool) -> Wallet | None:
    """Enable or disable tracking for a wallet without deleting it."""
    result = await session.execute(
        select(Wallet).where(Wallet.address == address)
    )
    wallet = result.scalar_one_or_none()
    if not wallet:
        return None
    wallet.active = active
    await session.commit()
    await session.refresh(wallet)
    logger.info("Toggled wallet %s active=%s", address, active)
    return wallet


async def get_active_addresses(session: AsyncSession) -> set[str]:
    """Return a set of active wallet addresses for fast lookup."""
    wallets = await list_wallets(session, active_only=True)
    return {w.address for w in wallets}


async def get_wallet_by_address(session: AsyncSession, address: str) -> Wallet | None:
    """Look up a single wallet by its on-chain address."""
    result = await session.execute(
        select(Wallet).where(Wallet.address == address)
    )
    return result.scalar_one_or_none()
