"""Backtesting harness.

Runs the full screening (and optionally would-be-execution) logic against
a directory of historical webhook fixtures, producing aggregate stats —
pass rate, would-be trade count, per-wallet breakdown — so screening
thresholds can be tuned against history before touching live config.
Built directly on simulation/dry_run_runner.py rather than duplicating
its replay logic; this module only adds aggregation and reporting.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.simulation.dry_run_runner import run_directory

logger = logging.getLogger(__name__)


@dataclass
class BacktestReport:
    fixtures_run: int = 0
    total_events: int = 0
    enriched_events: int = 0
    passed_screen: int = 0
    skip_reason_counts: dict[str, int] = field(default_factory=dict)
    per_wallet_pass_count: dict[str, int] = field(default_factory=dict)
    per_wallet_total_count: dict[str, int] = field(default_factory=dict)

    @property
    def pass_rate_pct(self) -> float:
        if self.total_events == 0:
            return 0.0
        return round(self.passed_screen / self.total_events * 100, 2)

    def wallet_pass_rate_pct(self, wallet: str) -> float:
        total = self.per_wallet_total_count.get(wallet, 0)
        if total == 0:
            return 0.0
        passed = self.per_wallet_pass_count.get(wallet, 0)
        return round(passed / total * 100, 2)


def _aggregate(raw_results: dict[str, list[dict[str, Any]]]) -> BacktestReport:
    report = BacktestReport(fixtures_run=len(raw_results))

    for results in raw_results.values():
        for r in results:
            report.total_events += 1
            wallet = r.get("wallet", "unknown")
            report.per_wallet_total_count[wallet] = (
                report.per_wallet_total_count.get(wallet, 0) + 1
            )

            if r.get("enriched"):
                report.enriched_events += 1

            if r.get("passed_screen"):
                report.passed_screen += 1
                report.per_wallet_pass_count[wallet] = (
                    report.per_wallet_pass_count.get(wallet, 0) + 1
                )
            elif r.get("skip_reasons"):
                for reason in r["skip_reasons"]:
                    # Collapse parameterized reasons ("market_cap_too_high (...)")
                    # down to their category for aggregate counting.
                    category = reason.split(" (")[0]
                    report.skip_reason_counts[category] = (
                        report.skip_reason_counts.get(category, 0) + 1
                    )

    return report


async def run_backtest(
    session: AsyncSession,
    fixtures_dir: Path,
    tracked_addresses: set[str],
) -> BacktestReport:
    """Replay every fixture in *fixtures_dir* and return an aggregate report.

    Does not sign or broadcast any transaction — delegates entirely to
    simulation.dry_run_runner for the replay itself.
    """
    raw_results = await run_directory(session, fixtures_dir, tracked_addresses)
    report = _aggregate(raw_results)

    logger.info(
        "Backtest complete — %d fixture(s), %d event(s), pass rate %.1f%%",
        report.fixtures_run,
        report.total_events,
        report.pass_rate_pct,
    )
    return report


def format_report_summary(report: BacktestReport) -> str:
    """Render a plain-text summary of a backtest report."""
    lines = [
        f"Backtest: {report.fixtures_run} fixture(s), {report.total_events} event(s)",
        f"Pass rate: {report.pass_rate_pct}% ({report.passed_screen}/{report.total_events})",
    ]
    if report.skip_reason_counts:
        lines.append("Top skip reasons:")
        for reason, count in sorted(
            report.skip_reason_counts.items(), key=lambda kv: -kv[1]
        )[:5]:
            lines.append(f"  - {reason}: {count}")
    return "\n".join(lines)
