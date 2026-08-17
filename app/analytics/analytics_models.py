"""Data classes for analytics — additive to core ORM models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class WalletScorecardDataclass:
    """Read-only view of a wallet's performance metrics."""

    wallet_id: str
    wallet_address: str
    total_alerts: int = 0
    passed_alerts: int = 0
    would_be_pnl: Decimal = Decimal("0")
    avg_return_pct: Decimal | None = None
    last_alert_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def pass_rate(self) -> float:
        if self.total_alerts == 0:
            return 0.0
        return round(self.passed_alerts / self.total_alerts * 100, 2)


@dataclass
class ConfluenceEventDataclass:
    """Read-only view of a multi-whale confluence detection."""

    token_mint: str
    wallet_addresses: list[str] = field(default_factory=list)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    alert_count: int = 0

    @property
    def confidence_boost(self) -> bool:
        return len(self.wallet_addresses) >= 2
