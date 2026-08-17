"""Tranche-based partial exit logic.

Instead of selling an entire position in one shot, scales out in
configurable tranches to reduce exposure to a single bad exit price.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TRANCHES = 3


@dataclass(frozen=True)
class Tranche:
    index: int
    size: Decimal
    percentage_of_position: Decimal


def calculate_tranches(
    position_size: Decimal,
    tranches: int = _DEFAULT_TRANCHES,
) -> list[Tranche]:
    """Split a position into equal-sized exit tranches.

    Returns a list of Tranche objects. The last tranche absorbs any
    rounding remainder so the sum always equals *position_size*.
    """
    if tranches <= 0:
        raise ValueError("tranches must be positive")
    if position_size <= 0:
        raise ValueError("position_size must be positive")

    base = position_size / Decimal(str(tranches))
    result: list[Tranche] = []
    total_so_far = Decimal("0")

    for i in range(tranches):
        if i == tranches - 1:
            size = position_size - total_so_far
        else:
            size = base
        total_so_far += size
        pct = (size / position_size) * Decimal("100")
        result.append(Tranche(index=i, size=size, percentage_of_position=pct))

    return result


def get_next_exit_tranche(
    position_size: Decimal,
    already_exited: Decimal,
    tranches: int = _DEFAULT_TRANCHES,
) -> Tranche | None:
    """Return the next tranche to exit, or None if the position is fully exited.

    *already_exited* is the cumulative amount already sold.
    """
    if already_exited >= position_size:
        return None

    all_tranches = calculate_tranches(position_size, tranches)
    cumulative = Decimal("0")
    for t in all_tranches:
        cumulative += t.size
        if cumulative > already_exited:
            return t

    return None
