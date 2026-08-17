"""Trailing stop-loss.

Tracks a position's peak price since entry and signals an exit if price
drops more than the configured trail percentage off that peak — an
automated safety exit independent of whether the whale being copied has
sold yet. This is a pure, stateless calculation module; the caller is
responsible for persisting TrailingStopState between price checks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from decimal import Decimal

from app.config import yaml_settings

logger = logging.getLogger(__name__)


def _trail_pct() -> Decimal:
    raw = yaml_settings.trailing_stop.get("trail_pct", 15)
    return Decimal(str(raw))


@dataclass(frozen=True)
class TrailingStopState:
    entry_price: Decimal
    peak_price: Decimal
    trail_pct: Decimal


def init_trailing_stop(entry_price: Decimal, trail_pct: Decimal | None = None) -> TrailingStopState:
    """Create the initial trailing-stop state for a new position."""
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    return TrailingStopState(
        entry_price=entry_price,
        peak_price=entry_price,
        trail_pct=trail_pct if trail_pct is not None else _trail_pct(),
    )


def update_peak(state: TrailingStopState, current_price: Decimal) -> TrailingStopState:
    """Return updated state with peak_price raised if current_price is a new high.

    Never lowers peak_price — the trail only ratchets up with price, per
    standard trailing-stop semantics.
    """
    if current_price > state.peak_price:
        return replace(state, peak_price=current_price)
    return state


def stop_price(state: TrailingStopState) -> Decimal:
    """Return the current trigger price — trail_pct below the peak."""
    return state.peak_price * (Decimal("1") - state.trail_pct / Decimal("100"))


def should_trigger_exit(state: TrailingStopState, current_price: Decimal) -> bool:
    """Return True if current_price has fallen through the trailing-stop trigger."""
    triggered = current_price <= stop_price(state)
    if triggered:
        logger.info(
            "Trailing stop triggered — entry=%s peak=%s current=%s trigger=%s",
            state.entry_price,
            state.peak_price,
            current_price,
            stop_price(state),
        )
    return triggered
