"""Tests for execution/partial_exit.py."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.execution.partial_exit import calculate_tranches, get_next_exit_tranche


class TestCalculateTranches:
    def test_three_equal_tranches(self) -> None:
        tranches = calculate_tranches(Decimal("300"), tranches=3)
        assert len(tranches) == 3
        assert tranches[0].size == Decimal("100")
        assert tranches[1].size == Decimal("100")
        assert tranches[2].size == Decimal("100")
        assert sum(t.size for t in tranches) == Decimal("300")

    def test_uneven_split(self) -> None:
        tranches = calculate_tranches(Decimal("100"), tranches=3)
        assert len(tranches) == 3
        assert sum(t.size for t in tranches) == Decimal("100")
        # Last tranche absorbs remainder
        assert tranches[2].size == Decimal("100") - tranches[0].size - tranches[1].size

    def test_invalid_tranches(self) -> None:
        with pytest.raises(ValueError):
            calculate_tranches(Decimal("100"), tranches=0)

    def test_invalid_position_size(self) -> None:
        with pytest.raises(ValueError):
            calculate_tranches(Decimal("0"), tranches=3)


class TestGetNextExitTranche:
    def test_first_tranche(self) -> None:
        t = get_next_exit_tranche(Decimal("300"), Decimal("0"), tranches=3)
        assert t is not None
        assert t.index == 0

    def test_second_tranche(self) -> None:
        t = get_next_exit_tranche(Decimal("300"), Decimal("100"), tranches=3)
        assert t is not None
        assert t.index == 1

    def test_fully_exited(self) -> None:
        t = get_next_exit_tranche(Decimal("300"), Decimal("300"), tranches=3)
        assert t is None

    def test_over_exited(self) -> None:
        t = get_next_exit_tranche(Decimal("300"), Decimal("400"), tranches=3)
        assert t is None
