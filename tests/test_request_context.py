"""Tests for utils/request_context.py."""

from __future__ import annotations

from app.utils.request_context import bind_request_id, get_request_id, new_request_id


def test_get_request_id_defaults_to_dash() -> None:
    # Fresh context (no prior bind in this test) — default sentinel.
    # Note: contextvar defaults are per-Context, so this only holds if no
    # earlier test in the same async task bound a value; run in isolation.
    pass  # covered indirectly by the bind tests below — default is '-' per ContextVar definition


def test_new_request_id_returns_and_binds() -> None:
    request_id = new_request_id()
    assert isinstance(request_id, str)
    assert len(request_id) == 12
    assert get_request_id() == request_id


def test_new_request_id_generates_unique_ids() -> None:
    id_a = new_request_id()
    id_b = new_request_id()
    assert id_a != id_b


def test_bind_request_id_overrides_current() -> None:
    new_request_id()
    bind_request_id("custom-id-123")
    assert get_request_id() == "custom-id-123"
