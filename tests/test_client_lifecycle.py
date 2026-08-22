"""Testes de ciclo de vida e estado do ProfitClient: connect, disconnect, context manager."""

from __future__ import annotations

import threading
import time

import pytest

from profitdll_wrapper import (
    AuthError,
    Event,
    ExchangeCode,
    ProfitClient,
    ProfitConnectionError,
)
from profitdll_wrapper._bindings.enums import ROUTING_STATES, ConnectionState, LoginResult
from tests.fakes.backend import FakeProfitBackend


def _client(backend: FakeProfitBackend, **kwargs: object) -> ProfitClient:
    defaults: dict[str, object] = {
        "activation_key": "key",
        "user": "user",
        "password": "pass",
        "mode": "market_data",
        "backend": backend,
    }
    defaults.update(kwargs)
    return ProfitClient(**defaults)  # type: ignore[arg-type]


class TestConnect:
    def test_connect_market_data_uses_market_login(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        assert client.is_connected
        assert fake_backend.initialize_calls == ["market_data"]
        assert fake_backend.set_trade_cb_calls >= 1
        client.disconnect()

    def test_connect_routing_uses_login(self) -> None:
        backend = FakeProfitBackend()
        backend.connect_states = ROUTING_STATES
        client = ProfitClient(
            activation_key="k",
            user="u",
            password="p",
            mode="routing",
            backend=backend,
        )
        client.connect(timeout=2.0)
        assert client.is_connected
        assert backend.initialize_calls == ["routing"]
        client.disconnect()

    def test_connect_raises_on_login_failure(self, fake_backend: FakeProfitBackend) -> None:
        fake_backend.connect_states = frozenset()
        client = _client(fake_backend)

        def _emit_fail() -> None:
            time.sleep(0.05)
            fake_backend.emit_state(ConnectionState.LOGIN, int(LoginResult.INVALID_PASS))

        threading.Thread(target=_emit_fail, daemon=True).start()

        with pytest.raises(AuthError):
            client.connect(timeout=2.0)

    def test_connect_raises_on_timeout(self, fake_backend: FakeProfitBackend) -> None:
        fake_backend.connect_states = frozenset()
        client = _client(fake_backend)
        with pytest.raises(ProfitConnectionError):
            client.connect(timeout=0.2)

    def test_invalid_mode_raises(self, fake_backend: FakeProfitBackend) -> None:
        with pytest.raises(ValueError):
            _client(fake_backend, mode="bogus")


class TestContextManager:
    def test_context_manager_connects_and_disconnects(
        self, fake_backend: FakeProfitBackend
    ) -> None:
        with _client(fake_backend) as client:
            assert client.is_connected
            assert not fake_backend.finalized
        assert fake_backend.finalized


class TestPublicAPI:
    def test_exchange_code_exported(self) -> None:
        assert ExchangeCode.BOVESPA.value == "B"

    def test_event_values(self) -> None:
        assert Event.TRADE.value == "TRADE"
        assert Event.ERROR.value == "ERROR"
        assert Event.PRICE_LEVEL.value == "PRICE_LEVEL"
        assert Event.PRICE_SNAPSHOT.value == "PRICE_SNAPSHOT"
        assert Event.DAILY.value == "DAILY"
