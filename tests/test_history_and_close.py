"""Testes unitários para a Fase 2 do roadmap: GetHistoryTrades, GetLastDailyClose e SetEnabledHistOrder."""

from __future__ import annotations

import time

import pytest

from profitdll_wrapper import Event, ProfitClient, Trade
from profitdll_wrapper._bindings.enums import MARKET_DATA_STATES
from profitdll_wrapper._bindings.structures import TConnectorAssetIdentifier
from tests.fakes.backend import FakeProfitBackend


@pytest.fixture
def fake_backend() -> FakeProfitBackend:
    backend = FakeProfitBackend()
    backend.connect_states = MARKET_DATA_STATES
    return backend


@pytest.fixture
def client(fake_backend: FakeProfitBackend) -> ProfitClient:
    return ProfitClient(
        activation_key="fake_key",
        user="fake_user",
        password="fake_password",
        mode="market_data",
        backend=fake_backend,
    )


def test_set_enabled_hist_order(client: ProfitClient, fake_backend: FakeProfitBackend) -> None:
    with client:
        client.set_enabled_hist_order(True)
        assert fake_backend.enabled_hist_order is True

        client.set_enabled_hist_order(False)
        assert fake_backend.enabled_hist_order is False


def test_get_last_daily_close(client: ProfitClient, fake_backend: FakeProfitBackend) -> None:
    fake_backend.set_last_daily_close("PETR4", "B", 38.50, adjusted=True)
    fake_backend.set_last_daily_close("PETR4", "B", 40.00, adjusted=False)

    with client:
        close_adj = client.get_last_daily_close("PETR4", exchange="B", adjusted=True)
        assert close_adj == 38.50

        close_raw = client.get_last_daily_close("PETR4", exchange="B", adjusted=False)
        assert close_raw == 40.00


def test_get_history_trades_request_and_event(
    client: ProfitClient, fake_backend: FakeProfitBackend
) -> None:
    trades: list[Trade] = []

    @client.on(Event.HISTORICAL_TRADE)
    def on_hist_trade(t: Trade) -> None:
        trades.append(t)

    with client:
        client.get_history_trades(
            "VALE3", "01/08/2026 09:00:00", "04/08/2026 18:00:00", exchange="B"
        )
        assert fake_backend.history_trade_requests == [
            ("VALE3", "B", "01/08/2026 09:00:00", "04/08/2026 18:00:00")
        ]

        asset = TConnectorAssetIdentifier()
        asset.Version = 0
        asset.Ticker = "VALE3"
        asset.Exchange = "B"

        fake_backend.emit_history_trade(
            asset, "2026-08-01 10:00:00", price=62.50, qty=500, trade_id=99
        )
        time.sleep(0.1)

        assert len(trades) == 1
        assert trades[0].asset.ticker == "VALE3"
        assert trades[0].price == 62.50
        assert trades[0].quantity == 500
