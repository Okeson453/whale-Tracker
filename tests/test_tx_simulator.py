"""Tests for execution/tx_simulator.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.execution.tx_simulator import simulate_transaction


def _mock_response(json_data: dict, raise_for_status: bool = False):
    resp = MagicMock()
    resp.json.return_value = json_data
    if raise_for_status:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    else:
        resp.raise_for_status.return_value = None
    return resp


async def test_simulate_transaction_success() -> None:
    payload = {"result": {"value": {"err": None, "logs": ["ok"], "unitsConsumed": 1234}}}
    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_response(payload)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await simulate_transaction("base64tx")

    assert result.ok is True
    assert result.units_consumed == 1234


async def test_simulate_transaction_program_error() -> None:
    payload = {
        "result": {
            "value": {
                "err": {"InstructionError": [0, "Custom"]},
                "logs": ["Program log: insufficient lamports for rent"],
            }
        }
    }
    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_response(payload)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await simulate_transaction("base64tx")

    assert result.ok is False
    assert result.reason == "insufficient_sol_for_rent_or_gas"


async def test_simulate_transaction_slippage_error() -> None:
    payload = {
        "result": {
            "value": {
                "err": {"InstructionError": [0, "Custom"]},
                "logs": ["Program log: slippage tolerance exceeded"],
            }
        }
    }
    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_response(payload)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await simulate_transaction("base64tx")

    assert result.ok is False
    assert result.reason == "slippage_exceeded"


async def test_simulate_transaction_rpc_error_field() -> None:
    payload = {"error": {"code": -32602, "message": "invalid params"}}
    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_response(payload)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await simulate_transaction("base64tx")

    assert result.ok is False
    assert "rpc_error" in result.reason


async def test_simulate_transaction_network_failure_fails_closed() -> None:
    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.side_effect = Exception("connection refused")
        result = await simulate_transaction("base64tx")

    assert result.ok is False
    assert "rpc_call_failed" in result.reason
