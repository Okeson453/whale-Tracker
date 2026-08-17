"""Unified configuration: secrets from .env, tunables from settings.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent


class _EnvSettings(BaseSettings):
    """Secrets and runtime overrides loaded from environment."""

    helius_api_key: str = ""
    helius_webhook_secret: str = ""
    solana_rpc_url: str = "https://api.devnet.solana.com"
    trader_private_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    database_url: str = f"sqlite+aiosqlite:///{_PROJECT_ROOT.parent}/data/whale_tracker.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


class _YamlSettings:
    """Non-secret tunables loaded from settings.yaml."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (_PROJECT_ROOT / "settings.yaml")
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        with open(self._path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    @property
    def screening(self) -> dict[str, Any]:
        return self._data.get("screening", {})

    @property
    def execution(self) -> dict[str, Any]:
        return self._data.get("execution", {})

    @property
    def circuit_breaker(self) -> dict[str, Any]:
        return self._data.get("circuit_breaker", {})

    @property
    def analytics(self) -> dict[str, Any]:
        return self._data.get("analytics", {})

    @property
    def whitelist(self) -> dict[str, Any]:
        return self._data.get("whitelist", {})

    @property
    def monitoring(self) -> dict[str, Any]:
        return self._data.get("monitoring", {})

    @property
    def wallet_clustering(self) -> dict[str, Any]:
        return self._data.get("wallet_clustering", {})

    @property
    def narrative(self) -> dict[str, Any]:
        return self._data.get("narrative", {})

    @property
    def dynamic_sizing(self) -> dict[str, Any]:
        return self._data.get("dynamic_sizing", {})

    @property
    def trailing_stop(self) -> dict[str, Any]:
        return self._data.get("trailing_stop", {})

    @property
    def exposure_cap(self) -> dict[str, Any]:
        return self._data.get("exposure_cap", {})

    @property
    def post_trade_review(self) -> dict[str, Any]:
        return self._data.get("post_trade_review", {})


# Global singletons — imported by modules
env = _EnvSettings()
yaml_settings = _YamlSettings()


def get_db_url() -> str:
    return env.database_url


class ConfigValidationError(Exception):
    """Raised at startup when settings.yaml or DATABASE_URL fail validation."""


# Expected top-level settings.yaml sections and the type each key within
# them must be. Not exhaustive of every optional key — this catches the
# failure mode that actually bites in practice: a typo'd key name (silently
# ignored by _YamlSettings.get()) or a value of the wrong type (e.g. a
# quoted string where a number was needed), not every possible misconfiguration.
_SETTINGS_SCHEMA: dict[str, dict[str, type]] = {
    "screening": {
        "max_market_cap_usd": (int, float),
        "min_liquidity_usd": (int, float),
        "max_rugcheck_score": (int, float),
        "min_buy_usd": (int, float),
    },
    "execution": {
        "mode": str,
        "approval_window_seconds": (int, float),
        "max_slippage_bps": (int, float),
        "position_cap_pct": (int, float),
    },
    "circuit_breaker": {
        "daily_loss_halt_pct": (int, float),
        "max_trades_per_day": (int, float),
    },
}


def validate_settings_schema(data: dict[str, Any] | None = None) -> list[str]:
    """Check settings.yaml against the expected shape for core sections.

    Returns a list of human-readable problems (empty if none). Does not
    raise on its own — callers decide whether a problem is fatal (see
    ``validate_startup_config``) so this stays usable from tests without
    needing to catch an exception.
    """
    data = data if data is not None else yaml_settings._data
    problems: list[str] = []

    for section, fields in _SETTINGS_SCHEMA.items():
        section_data = data.get(section)
        if section_data is None:
            problems.append(f"settings.yaml missing expected section: '{section}'")
            continue
        if not isinstance(section_data, dict):
            problems.append(f"settings.yaml section '{section}' must be a mapping")
            continue
        for key, expected_type in fields.items():
            if key not in section_data:
                problems.append(f"settings.yaml '{section}.{key}' is missing")
                continue
            value = section_data[key]
            if isinstance(value, bool) or not isinstance(value, expected_type):
                problems.append(
                    f"settings.yaml '{section}.{key}' should be "
                    f"{expected_type}, got {type(value).__name__} ({value!r})"
                )

    return problems


def validate_database_url(url: str | None = None) -> list[str]:
    """Check that DATABASE_URL is a well-formed SQLAlchemy async URL.

    Returns a list of problems (empty if none). Catches the specific
    failure mode of a malformed Postgres URL reaching aiosqlite/asyncpg
    at connection time instead of at startup.
    """
    url = url if url is not None else env.database_url
    problems: list[str] = []

    if not url:
        problems.append("DATABASE_URL is empty")
        return problems

    if "://" not in url:
        problems.append(f"DATABASE_URL is not a valid URL: {url!r}")
        return problems

    scheme = url.split("://", 1)[0]
    if "+" not in scheme:
        problems.append(
            f"DATABASE_URL scheme '{scheme}' is missing an async driver "
            f"(expected e.g. 'sqlite+aiosqlite' or 'postgresql+asyncpg')"
        )

    if scheme.startswith("postgresql") and "asyncpg" not in scheme:
        problems.append(
            f"DATABASE_URL scheme '{scheme}' should use the asyncpg driver "
            f"for async SQLAlchemy (postgresql+asyncpg://...)"
        )

    return problems


def validate_startup_config() -> None:
    """Fail fast on startup if settings.yaml or DATABASE_URL are malformed.

    Raises ConfigValidationError with every problem found (not just the
    first) so a misconfiguration is fixed in one pass instead of
    discovered one field at a time across repeated restarts.
    """
    problems = validate_settings_schema() + validate_database_url()
    if problems:
        raise ConfigValidationError(
            "Startup config validation failed:\n" + "\n".join(f"  - {p}" for p in problems)
        )
