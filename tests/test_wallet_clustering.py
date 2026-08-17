"""Tests for analytics/wallet_clustering.py."""

from __future__ import annotations

from app.analytics.wallet_clustering import (
    compute_co_occurrences,
    count_independent_wallets,
    get_cluster_for_address,
    refresh_clusters,
)
from app.state.models import ConfluenceEvent, WalletCluster


async def _seed_confluence(session, token_mint: str, wallets: list[str]) -> None:
    event = ConfluenceEvent(
        token_mint=token_mint,
        wallet_addresses=wallets,
        alert_count=len(wallets),
    )
    session.add(event)
    await session.commit()


async def test_compute_co_occurrences_below_threshold_excluded(session) -> None:
    await _seed_confluence(session, "TOKEN1", ["A", "B"])
    pairs = await compute_co_occurrences(session, min_co_occurrences=3)
    assert pairs == {}


async def test_compute_co_occurrences_meets_threshold(session) -> None:
    for i in range(3):
        await _seed_confluence(session, f"TOKEN{i}", ["A", "B"])
    pairs = await compute_co_occurrences(session, min_co_occurrences=3)
    assert pairs.get(("A", "B")) == 3


async def test_refresh_clusters_groups_wallets(session) -> None:
    for i in range(3):
        await _seed_confluence(session, f"TOKEN{i}", ["A", "B"])
    clusters = await refresh_clusters(session, min_co_occurrences=3)
    assert len(clusters) == 1
    assert sorted(clusters[0].wallet_ids) == ["A", "B"]


async def test_refresh_clusters_transitive_grouping(session) -> None:
    for i in range(3):
        await _seed_confluence(session, f"TOKENAB{i}", ["A", "B"])
    for i in range(3):
        await _seed_confluence(session, f"TOKENBC{i}", ["B", "C"])
    clusters = await refresh_clusters(session, min_co_occurrences=3)
    assert len(clusters) == 1
    assert sorted(clusters[0].wallet_ids) == ["A", "B", "C"]


async def test_get_cluster_for_address(session) -> None:
    for i in range(3):
        await _seed_confluence(session, f"TOKEN{i}", ["A", "B"])
    await refresh_clusters(session, min_co_occurrences=3)
    cluster = await get_cluster_for_address(session, "A")
    assert cluster is not None
    assert "B" in cluster.wallet_ids

    none_cluster = await get_cluster_for_address(session, "Z")
    assert none_cluster is None


def test_count_independent_wallets_collapses_cluster() -> None:
    cluster = WalletCluster(id="c1", wallet_ids=["A", "B"], co_occurrence_count=5)
    count = count_independent_wallets(["A", "B", "C"], [cluster])
    assert count == 2  # A+B collapse to one actor, C is independent


def test_count_independent_wallets_no_clusters() -> None:
    count = count_independent_wallets(["A", "B", "C"], [])
    assert count == 3
