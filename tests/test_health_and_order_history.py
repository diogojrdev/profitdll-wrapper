"""Testes unitários para o Watchdog de integridade (v4.0.0.41) e histórico de ordens."""

from __future__ import annotations

import time

import pytest

from profitdll_wrapper import Event, ProfitClient, SystemHealthState
from profitdll_wrapper._bindings.enums import ROUTING_STATES
from tests.fakes.backend import FakeProfitBackend


@pytest.fixture
def fake_backend() -> FakeProfitBackend:
    backend = FakeProfitBackend()
    backend.connect_states = ROUTING_STATES
    return backend


@pytest.fixture
def client(fake_backend: FakeProfitBackend) -> ProfitClient:
    return ProfitClient(
        activation_key="fake_key",
        user="fake_user",
        password="fake_password",
        mode="routing",
        backend=fake_backend,
        broker_id=150,
    )


def test_get_health_status_responsive_default(
    client: ProfitClient, fake_backend: FakeProfitBackend
) -> None:
    with client:
        health = client.get_health_status()
        assert health == SystemHealthState.RESPONSIVE
        assert health.value == 0


def test_get_health_status_frozen(client: ProfitClient, fake_backend: FakeProfitBackend) -> None:
    with client:
        fake_backend._health_status = 1
        health = client.get_health_status()
        assert health == SystemHealthState.FROZEN
        assert health.value == 1


def test_health_change_event_callback(
    client: ProfitClient, fake_backend: FakeProfitBackend
) -> None:
    events: list[SystemHealthState] = []

    @client.on(Event.HEALTH_CHANGE)
    def on_health(state: SystemHealthState) -> None:
        events.append(state)

    with client:
        fake_backend.emit_health_change(1)
        time.sleep(0.1)

        assert len(events) == 1
        assert events[0] == SystemHealthState.FROZEN


def test_get_order_history_empty(client: ProfitClient, fake_backend: FakeProfitBackend) -> None:
    with client:
        orders = client.get_order_history("12345")
        assert orders == []


def test_get_order_history_interval_empty(
    client: ProfitClient, fake_backend: FakeProfitBackend
) -> None:
    with client:
        orders = client.get_order_history("12345", start_date="2026-08-01", end_date="2026-08-04")
        assert orders == []
