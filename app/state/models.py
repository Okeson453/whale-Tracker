"""SQLAlchemy ORM models — wallets, swap_events, token_profiles, alerts, trades, daily_state."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum as PyEnum
from typing import List

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Wallet(Base):
    """Tracked whale wallets."""

    __tablename__ = "wallets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    address: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    swap_events: Mapped[List["SwapEvent"]] = relationship(
        back_populates="wallet", cascade="all, delete-orphan"
    )


class SwapEvent(Base):
    """Raw buy detections from webhook ingestion."""

    __tablename__ = "swap_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    wallet_id: Mapped[str] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False
    )
    token_mint: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    signature: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    wallet: Mapped["Wallet"] = relationship(back_populates="swap_events")

    __table_args__ = (UniqueConstraint("signature", name="uq_swap_event_signature"),)


class TokenProfile(Base):
    """Enrichment snapshot for a token mint — cached, short TTL."""

    __tablename__ = "token_profiles"

    token_mint: Mapped[str] = mapped_column(Text, primary_key=True)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(36, 6), nullable=True)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(36, 6), nullable=True
    )
    volume_24h: Mapped[Decimal | None] = mapped_column(
        Numeric(36, 6), nullable=True
    )
    price_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(36, 18), nullable=True
    )
    rugcheck_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risks: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


class AlertDecision(str, PyEnum):
    pending = "pending"
    executed = "executed"
    passed_by_human = "passed_by_human"
    expired = "expired"


class Alert(Base):
    """Screening outcomes + human decisions."""

    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    swap_event_id: Mapped[str] = mapped_column(
        ForeignKey("swap_events.id", ondelete="CASCADE"), nullable=False
    )
    passed_screen: Mapped[bool] = mapped_column(Boolean, nullable=False)
    skip_reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    decision: Mapped[str] = mapped_column(
        String(20), default=AlertDecision.pending.value, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Number of distinct tracked wallets seen buying this token within the
    # confluence window at the time this alert was generated (>=2 means
    # confluence_detector.check_confluence found a boost). Null when the
    # alert didn't pass screening, since confluence is only checked for
    # screened-in buys.
    confluence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    swap_event: Mapped["SwapEvent"] = relationship(back_populates="alerts")


SwapEvent.alerts = relationship("Alert", back_populates="swap_event", cascade="all, delete-orphan")


class TradeStatus(str, PyEnum):
    submitted = "submitted"
    confirmed = "confirmed"
    failed = "failed"


class Trade(Base):
    """Executed transactions only."""

    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    alert_id: Mapped[str | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), nullable=True
    )
    tx_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    usd_value: Mapped[Decimal | None] = mapped_column(Numeric(36, 6), nullable=True)
    slippage_actual: Mapped[Decimal | None] = mapped_column(
        Numeric(36, 6), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=TradeStatus.submitted.value, nullable=False
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


class DailyState(Base):
    """Circuit breaker bookkeeping."""

    __tablename__ = "daily_state"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    starting_balance: Mapped[Decimal] = mapped_column(
        Numeric(36, 6), nullable=False, default=Decimal("0")
    )
    trades_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    halted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PositionStatus(str, PyEnum):
    open = "open"
    closed = "closed"
    exit_failed = "exit_failed"


class Position(Base):
    """An open copy-trade position — links a whale wallet to what we hold.

    Created when a whale buy is auto-copied; closed out when that same
    whale sells the same token (blind mirroring) or by a manual/other exit
    path. One row per (wallet, token_mint) while open — a second buy from
    the same whale into the same token while a position is already open
    tops up ``amount_held`` rather than creating a duplicate row.
    """

    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    wallet_id: Mapped[str] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False
    )
    token_mint: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    entry_trade_id: Mapped[str] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), nullable=False
    )
    exit_trade_id: Mapped[str | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), nullable=True
    )
    amount_held: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    entry_usd_value: Mapped[Decimal | None] = mapped_column(
        Numeric(36, 6), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=PositionStatus.open.value, nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # No DB-level uniqueness on (wallet_id, token_mint): a wallet can be
    # copy-bought/sold many times over history. "Only one open position per
    # (wallet, token) at a time" is enforced in copy_trade_engine at lookup
    # time (query filters status == open), not here.


class WalletScorecard(Base):
    """Per-whale win-rate and would-be PnL tracking."""

    __tablename__ = "wallet_scorecards"

    wallet_id: Mapped[str] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"), primary_key=True
    )
    total_alerts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_alerts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    would_be_pnl: Mapped[Decimal] = mapped_column(
        Numeric(36, 6), default=Decimal("0"), nullable=False
    )
    avg_return_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(36, 6), nullable=True
    )
    last_alert_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )

    wallet: Mapped["Wallet"] = relationship(back_populates="scorecard")


Wallet.scorecard = relationship(
    "WalletScorecard", back_populates="wallet", uselist=False, cascade="all, delete-orphan"
)


class ConfluenceEvent(Base):
    """Multi-whale buy confluence detection."""

    __tablename__ = "confluence_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    token_mint: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    wallet_addresses: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    alert_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class WalletCluster(Base):
    """Groups of tracked wallets suspected to be the same entity.

    Populated by correlated buy-timing analysis (repeated near-simultaneous
    buys of the same token), not by any on-chain funding-source proof —
    membership is a hypothesis for weighting confluence signals, not a claim.
    """

    __tablename__ = "wallet_clusters"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    wallet_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    co_occurrence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )


class NarrativeScore(Base):
    """Cached social/narrative signal for a token — secondary filter only."""

    __tablename__ = "narrative_scores"

    token_mint: Mapped[str] = mapped_column(Text, primary_key=True)
    mention_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentiment_score: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


class PostTradeReview(Base):
    """Flags trades whose actual execution deviated from the guardrail estimate."""

    __tablename__ = "post_trade_reviews"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    trade_id: Mapped[str] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), nullable=False
    )
    expected_slippage_bps: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    actual_slippage_bps: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    expected_fill_seconds: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    actual_fill_seconds: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flag_reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
