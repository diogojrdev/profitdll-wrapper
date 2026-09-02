"""Tests for broker_id resolution and order-history date parsing."""

from __future__ import annotations

import pytest

from profitdll_wrapper import ProfitClient
from profitdll_wrapper._bindings.enums import ROUTING_STATES
from profitdll_wrapper.client._routing import _parse_system_time
from tests.fakes.backend import FakeProfitBackend


def _client(broker_id: int | None = None) -> ProfitClient:
    backend = FakeProfitBackend()
    backend.connect_states = ROUTING_STATES
    client = ProfitClient(
        activation_key="key",
        user="user",
        password="pass",
        mode="routing",
        routing_password="routing-pw",
        backend=backend,
        broker_id=broker_id,
    )
    client.connect()
    return client


def test_client_broker_id_used_when_argument_omitted() -> None:
    client = _client(broker_id=15003)
    assert client._resolve_broker_id(None, account="12345") == 15003
    assert client._resolve_broker_id(999, account="12345") == 999


def test_resolve_broker_id_raises_without_any_source() -> None:
    client = _client(broker_id=None)
    with pytest.raises(ValueError, match="broker_id could not be resolved"):
        client._resolve_broker_id(None, account="12345")


def test_get_order_history_requires_broker() -> None:
    client = _client(broker_id=None)
    with pytest.raises(ValueError, match="broker_id could not be resolved"):
        client.get_order_history("12345")


def test_parse_system_time_formats() -> None:
    br = _parse_system_time("21/08/2026 09:30:15")
    assert (br.wDay, br.wMonth, br.wYear, br.wHour, br.wMinute, br.wSecond) == (
        21,
        8,
        2026,
        9,
        30,
        15,
    )
    iso = _parse_system_time("2026-08-01")
    assert (iso.wDay, iso.wMonth, iso.wYear, iso.wHour) == (1, 8, 2026, 0)
    with pytest.raises(ValueError, match="Invalid date"):
        _parse_system_time("não-data")
