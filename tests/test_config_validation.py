"""Tests for config.py validate_settings_schema / validate_database_url."""

from __future__ import annotations

import pytest

from app.config import (
    ConfigValidationError,
    validate_database_url,
    validate_settings_schema,
    validate_startup_config,
)

_VALID_SETTINGS = {
    "screening": {
        "max_market_cap_usd": 5_000_000,
        "min_liquidity_usd": 50_000,
        "max_rugcheck_score": 500,
        "min_buy_usd": 500,
    },
    "execution": {
        "mode": "approval_gate",
        "approval_window_seconds": 20,
        "max_slippage_bps": 500,
        "position_cap_pct": 10,
    },
    "circuit_breaker": {
        "daily_loss_halt_pct": 20,
        "max_trades_per_day": 5,
    },
}


def test_validate_settings_schema_passes_on_valid_data() -> None:
    problems = validate_settings_schema(_VALID_SETTINGS)
    assert problems == []


def test_validate_settings_schema_flags_missing_section() -> None:
    data = {k: v for k, v in _VALID_SETTINGS.items() if k != "circuit_breaker"}
    problems = validate_settings_schema(data)
    assert any("circuit_breaker" in p for p in problems)


def test_validate_settings_schema_flags_missing_key() -> None:
    import copy

    data = copy.deepcopy(_VALID_SETTINGS)
    del data["screening"]["min_buy_usd"]
    problems = validate_settings_schema(data)
    assert any("screening.min_buy_usd" in p for p in problems)


def test_validate_settings_schema_flags_wrong_type() -> None:
    import copy

    data = copy.deepcopy(_VALID_SETTINGS)
    data["screening"]["max_market_cap_usd"] = "five million"  # should be numeric
    problems = validate_settings_schema(data)
    assert any("screening.max_market_cap_usd" in p for p in problems)


def test_validate_settings_schema_rejects_bool_for_numeric_field() -> None:
    import copy

    data = copy.deepcopy(_VALID_SETTINGS)
    data["circuit_breaker"]["max_trades_per_day"] = True  # bool is not a valid number here
    problems = validate_settings_schema(data)
    assert any("circuit_breaker.max_trades_per_day" in p for p in problems)


def test_validate_database_url_accepts_sqlite_async() -> None:
    problems = validate_database_url("sqlite+aiosqlite:///./data/whale_tracker.db")
    assert problems == []


def test_validate_database_url_accepts_postgres_async() -> None:
    problems = validate_database_url("postgresql+asyncpg://user:pass@host/db")
    assert problems == []


def test_validate_database_url_flags_missing_async_driver() -> None:
    problems = validate_database_url("sqlite:///./data/whale_tracker.db")
    assert any("async driver" in p for p in problems)


def test_validate_database_url_flags_postgres_without_asyncpg() -> None:
    problems = validate_database_url("postgresql+psycopg2://user:pass@host/db")
    assert any("asyncpg" in p for p in problems)


def test_validate_database_url_flags_empty() -> None:
    problems = validate_database_url("")
    assert any("empty" in p for p in problems)


def test_validate_database_url_flags_malformed() -> None:
    problems = validate_database_url("not-a-url-at-all")
    assert problems  # non-empty


def test_validate_startup_config_raises_on_missing_sections(monkeypatch) -> None:
    import app.config as config_module

    monkeypatch.setattr(config_module.yaml_settings, "_data", {})
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_startup_config()
    assert "screening" in str(exc_info.value)


def test_validate_startup_config_passes_on_valid_data(monkeypatch) -> None:
    import app.config as config_module

    monkeypatch.setattr(config_module.yaml_settings, "_data", _VALID_SETTINGS)
    monkeypatch.setattr(config_module.env, "database_url", "sqlite+aiosqlite:///./data/test.db")
    validate_startup_config()  # should not raise
