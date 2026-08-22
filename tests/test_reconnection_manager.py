"""Testes do Reconnection Manager & Auto-Resubscribe no ProfitClient."""

from __future__ import annotations

from profitdll_wrapper import ProfitClient
from profitdll_wrapper._bindings.enums import ConnectionState, MarketResult
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


class TestReconnectionManager:
    def test_subscription_tracking(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        # Test active tracking
        client.subscribe("PETR4", exchange="B")
        client.subscribe_price_depth("VALE3", exchange="B")
        client.subscribe_offer_book("WINQ26", exchange="F")
        client.subscribe_adjust_history("ITUB4", exchange="B")

        assert ("ticker", "PETR4", "B") in client._active_subscriptions
        assert ("price_depth", "VALE3", "B") in client._active_subscriptions
        assert ("offer_book", "WINQ26", "F") in client._active_subscriptions
        assert ("adjust_history", "ITUB4", "B") in client._active_subscriptions

        # Test untracking on unsubscribe
        client.unsubscribe("PETR4", exchange="B")
        client.unsubscribe_price_depth("VALE3", exchange="B")

        assert ("ticker", "PETR4", "B") not in client._active_subscriptions
        assert ("price_depth", "VALE3", "B") not in client._active_subscriptions
        assert ("offer_book", "WINQ26", "F") in client._active_subscriptions

        client.disconnect()

    def test_manual_resubscribe_all(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        client.subscribe("PETR4", exchange="B")
        client.subscribe_price_depth("VALE3", exchange="B")
        fake_backend.subscribed.clear()
        fake_backend.subscribed_depth.clear()

        restored_count = client.resubscribe_all()
        assert restored_count == 2
        assert ("PETR4", "B") in fake_backend.subscribed
        assert ("VALE3", "B") in fake_backend.subscribed_depth

        client.disconnect()

    def test_auto_resubscribe_on_reconnect(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend, auto_resubscribe=True)
        client.connect(timeout=2.0)

        client.subscribe("PETR4", exchange="B")
        client.subscribe_price_depth("VALE3", exchange="B")

        # Clear backend call counters to isolate reconnection calls
        fake_backend.subscribed.clear()
        fake_backend.subscribed_depth.clear()

        # Simulate disconnection and reconnection state callback
        # 1) Disconnected state
        fake_backend.state_callback(
            int(ConnectionState.MARKET_DATA), int(MarketResult.DISCONNECTED)
        )
        # 2) Reconnected state
        fake_backend.state_callback(int(ConnectionState.MARKET_DATA), int(MarketResult.CONNECTED))

        # Assert resubscribe calls were automatically issued
        assert ("PETR4", "B") in fake_backend.subscribed
        assert ("VALE3", "B") in fake_backend.subscribed_depth

        client.disconnect()

    def test_auto_resubscribe_disabled(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend, auto_resubscribe=False)
        client.connect(timeout=2.0)

        client.subscribe("PETR4", exchange="B")
        fake_backend.subscribed.clear()

        # Simulate reconnection state callback
        fake_backend.state_callback(
            int(ConnectionState.MARKET_DATA), int(MarketResult.DISCONNECTED)
        )
        fake_backend.state_callback(int(ConnectionState.MARKET_DATA), int(MarketResult.CONNECTED))

        # Re-subscribe should NOT have been called automatically
        assert len(fake_backend.subscribed) == 0

        client.disconnect()
