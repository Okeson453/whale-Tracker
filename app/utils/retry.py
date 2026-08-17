"""Exponential backoff retry helper.

Enrichment API calls currently fail-closed on the first timeout (return
None immediately) — correct for correctness, but wasteful for a single
transient blip on a flaky upstream. This wraps a single async HTTP call
with a small number of retries and exponential backoff before giving up
and returning to the existing fail-closed behavior.

Deliberately not a decorator that swallows all exceptions silently —
callers still see (and log) the final failure themselves; this only
governs how many attempts happen first.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 4.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    op_name: str = "operation",
) -> T:
    """Call *fn* (a zero-arg async callable), retrying on failure.

    Delay doubles each attempt with +/-20% jitter, capped at
    *max_delay_seconds*. Re-raises the last exception if every attempt
    fails — callers keep their existing try/except-and-return-None
    pattern around this, so failure handling doesn't change, only the
    number of attempts before it kicks in.
    """
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except retry_on as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)
            delay *= random.uniform(0.8, 1.2)
            logger.debug(
                "%s attempt %d/%d failed (%s) — retrying in %.2fs",
                op_name,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc
