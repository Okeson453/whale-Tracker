"""Tests for utils/retry.py."""

from __future__ import annotations

import pytest

from app.utils.retry import retry_with_backoff


async def test_retry_succeeds_first_try() -> None:
    calls = []

    async def fn():
        calls.append(1)
        return "ok"

    result = await retry_with_backoff(fn, max_attempts=3, base_delay_seconds=0.01)
    assert result == "ok"
    assert len(calls) == 1


async def test_retry_succeeds_after_failures() -> None:
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"

    result = await retry_with_backoff(fn, max_attempts=3, base_delay_seconds=0.01)
    assert result == "ok"
    assert len(calls) == 3


async def test_retry_exhausts_and_raises() -> None:
    calls = []

    async def fn():
        calls.append(1)
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        await retry_with_backoff(fn, max_attempts=3, base_delay_seconds=0.01)
    assert len(calls) == 3


async def test_retry_only_catches_specified_exceptions() -> None:
    async def fn():
        raise KeyError("not retried")

    with pytest.raises(KeyError):
        await retry_with_backoff(
            fn, max_attempts=3, base_delay_seconds=0.01, retry_on=(ValueError,)
        )
