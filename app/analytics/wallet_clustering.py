"""Wallet clustering.

Detects when "independent" tracked wallets are repeatedly buying the same
tokens within a tight time window — a pattern consistent with the wallets
being controlled by the same entity. Membership here is a statistical
hypothesis derived purely from correlated timing, not a claim about
funding source or on-chain proof of common control. Its only downstream
use is to avoid double-counting a single actor's activity as independent
confluence (see analytics/confluence_detector.py).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import yaml_settings
from app.state.models import ConfluenceEvent, WalletCluster

logger = logging.getLogger(__name__)


def _thresholds() -> dict:
    return yaml_settings.wallet_clustering


async def compute_co_occurrences(
    session: AsyncSession,
    min_co_occurrences: int | None = None,
) -> dict[tuple[str, str], int]:
    """Count how often each pair of wallet addresses appears together in a
    ConfluenceEvent.

    Returns a mapping of (address_a, address_b) -> co-occurrence count,
    filtered to pairs meeting *min_co_occurrences*. Addresses within each
    pair key are sorted so (A, B) and (B, A) collapse to one entry.
    """
    threshold = min_co_occurrences or _thresholds().get("min_co_occurrences", 3)

    result = await session.execute(select(ConfluenceEvent))
    events = result.scalars().all()

    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for event in events:
        addresses = sorted(set(event.wallet_addresses))
        for a, b in combinations(addresses, 2):
            pair_counts[(a, b)] += 1

    return {
        pair: count for pair, count in pair_counts.items() if count >= threshold
    }


async def refresh_clusters(
    session: AsyncSession, min_co_occurrences: int | None = None
) -> list[WalletCluster]:
    """Recompute wallet clusters from confluence history and persist them.

    Uses simple union-find grouping: if wallet A clusters with B, and B
    clusters with C, all three land in one cluster. Existing clusters are
    replaced wholesale — this is a full recompute, not an incremental patch.
    """
    pair_counts = await compute_co_occurrences(session, min_co_occurrences)

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for a, b in pair_counts:
        union(a, b)

    groups: dict[str, set[str]] = defaultdict(set)
    for addr in parent:
        groups[find(addr)].add(addr)

    # Wipe existing clusters and re-persist — full recompute
    existing = (await session.execute(select(WalletCluster))).scalars().all()
    for cluster in existing:
        await session.delete(cluster)
    await session.flush()

    new_clusters: list[WalletCluster] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        member_list = sorted(members)
        total_occurrences = sum(
            count
            for pair, count in pair_counts.items()
            if pair[0] in members and pair[1] in members
        )
        cluster = WalletCluster(
            wallet_ids=member_list,
            co_occurrence_count=total_occurrences,
        )
        session.add(cluster)
        new_clusters.append(cluster)

    await session.commit()
    logger.info("Refreshed wallet clusters — %d cluster(s) found", len(new_clusters))
    return new_clusters


async def get_cluster_for_address(
    session: AsyncSession, wallet_address: str
) -> WalletCluster | None:
    """Return the cluster containing *wallet_address*, if any."""
    result = await session.execute(select(WalletCluster))
    for cluster in result.scalars().all():
        if wallet_address in cluster.wallet_ids:
            return cluster
    return None


def count_independent_wallets(
    wallet_addresses: list[str], clusters: list[WalletCluster]
) -> int:
    """Collapse *wallet_addresses* by cluster membership and return the
    count of independent actors.

    Used to correct a confluence signal: three wallets that are all
    members of the same cluster represent one independent actor, not three.
    """
    cluster_map: dict[str, str] = {}
    for cluster in clusters:
        for addr in cluster.wallet_ids:
            cluster_map[addr] = cluster.id

    seen: set[str] = set()
    independent_count = 0
    for addr in wallet_addresses:
        key = cluster_map.get(addr, addr)  # unclustered wallets count individually
        if key not in seen:
            seen.add(key)
            independent_count += 1

    return independent_count
