"""Request ID context — traces a single webhook through parse → enrich →
screen → alert without threading an explicit parameter through every
function signature in the pipeline.

Uses a contextvar rather than a global so concurrent requests (async,
potentially overlapping) don't clobber each other's request id.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    """Generate and bind a new request id for the current async context.

    Returns the generated id so the caller can also attach it to a
    response header (e.g. X-Request-ID) for the upstream provider to
    correlate retries.
    """
    request_id = uuid.uuid4().hex[:12]
    _request_id_var.set(request_id)
    return request_id


def get_request_id() -> str:
    """Return the request id bound in the current context, or '-' if none."""
    return _request_id_var.get()


def bind_request_id(request_id: str) -> None:
    """Bind an existing request id (e.g. one supplied by an upstream caller)."""
    _request_id_var.set(request_id)
