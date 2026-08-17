"""Simulated dry-run mode — replays historical webhook fixtures through
the full pipeline (parse → enrich → screen → alert) without ever signing
a transaction. Guardrails are evaluated but execution is stubbed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.enrichment.enrichment_service import enrich_token
from app.ingestion.tx_parser import parse_webhook_payload
from app.screening.rules_engine import screen_event
from app.state.models import SwapEvent, TokenProfile, Wallet

logger = logging.getLogger(__name__)


def load_fixture(path: Path) -> dict[str, Any] | list[Any]:
    """Load a JSON webhook fixture from disk."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


async def run_fixture(
    session: AsyncSession,
    fixture_path: Path,
    tracked_addresses: set[str],
) -> list[dict[str, Any]]:
    """Replay a single fixture through the full pipeline.

    Returns a list of result dicts showing parse → enrich → screen outcomes.
    No transactions are signed or broadcast.
    """
    payload = load_fixture(fixture_path)
    events = parse_webhook_payload(payload, tracked_addresses)
    results: list[dict[str, Any]] = []

    for evt in events:
        # Enrich (uses real APIs or mocks depending on test setup)
        profile = await enrich_token(evt.token_mint, session)

        # Screen
        if profile is not None:
            result = screen_event(evt, profile)
        else:
            result = None

        results.append(
            {
                "wallet": evt.wallet_address,
                "token_mint": evt.token_mint,
                "amount": str(evt.amount),
                "signature": evt.signature,
                "enriched": profile is not None,
                "screened": result is not None,
                "passed_screen": result.passed if result else None,
                "skip_reasons": result.reasons if result and not result.passed else None,
            }
        )

    logger.info(
        "Dry-run finished for %s — %d event(s), %d passed screening",
        fixture_path.name,
        len(results),
        sum(1 for r in results if r.get("passed_screen")),
    )
    return results


async def run_directory(
    session: AsyncSession,
    fixtures_dir: Path,
    tracked_addresses: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Replay every ``*.json`` fixture in *fixtures_dir*.

    Returns a mapping of filename → list of result dicts.
    """
    all_results: dict[str, list[dict[str, Any]]] = {}
    if not fixtures_dir.exists():
        logger.warning("Fixtures directory does not exist: %s", fixtures_dir)
        return all_results

    for fixture_path in sorted(fixtures_dir.glob("*.json")):
        all_results[fixture_path.name] = await run_fixture(
            session, fixture_path, tracked_addresses
        )

    total_events = sum(len(v) for v in all_results.values())
    total_passed = sum(
        1 for results in all_results.values() for r in results if r.get("passed_screen")
    )
    logger.info(
        "Dry-run batch complete — %d fixture(s), %d event(s), %d passed",
        len(all_results),
        total_events,
        total_passed,
    )
    return all_results
