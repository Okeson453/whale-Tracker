"""Data classes for screening results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScreeningResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
