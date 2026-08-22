"""Testes unitários para consulta e eventos de posição em custódia (Fase P2)."""

from __future__ import annotations

from profitdll_wrapper import Event, Position, ProfitClient
from profitdll_wrapper._bindings.enums import ROUTING_STATES
from profitdll_wrapper._bindings.structures import (
    TConnectorAccountIdentifier,
    TConnectorAssetIdentifier,
    TConnectorTradingAccountPosition,
)
from tests.fakes.backend import FakeProfitBackend


class TestPositionManagement:
    def test_get_position_empty(self, fake_backend: FakeProfitBackend) -> None:
        fake_backend.connect_states = ROUTING_STATES
        client = ProfitClient(
            activation_key="key",
            user="user",
            password="pass",
            mode="routing",
            backend=fake_backend,
            broker_id=150,
        )
        client.connect()

        pos = client.get_position("WDOFUT", exchange="F", account="12345")
        assert pos.asset.ticker == "WDOFUT"
        assert pos.quantity == 0
        assert pos.average_price == 0.0

    def test_get_position_with_data(self, fake_backend: FakeProfitBackend) -> None:
        fake_backend.connect_states = ROUTING_STATES
        client = ProfitClient(
            activation_key="key",
            user="user",
            password="pass",
            mode="routing",
            backend=fake_backend,
            broker_id=150,
        )
        client.connect()

        p_struct = TConnectorTradingAccountPosition()
        p_struct.Version = 0
        p_struct.DailyQuantity = 10
        p_struct.OpenAveragePrice = 5180.50
        p_struct.DailyBuyQuantity = 10
        p_struct.DailySellQuantity = 0
        p_struct.DailyAverageBuyPrice = 5180.50
        p_struct.DailyAverageSellPrice = 0.0

        fake_backend.set_mock_position("PETR4", "12345", p_struct)

        pos = client.get_position("PETR4", exchange="B", account="12345")
        assert pos.asset.ticker == "PETR4"
        assert pos.quantity == 10
        assert pos.average_price == 5180.50
        assert pos.buy_quantity == 10

    def test_position_event_received(self, fake_backend: FakeProfitBackend) -> None:
        fake_backend.connect_states = ROUTING_STATES
        client = ProfitClient(
            activation_key="key",
            user="user",
            password="pass",
            mode="routing",
            backend=fake_backend,
            broker_id=150,
        )
        client.connect()

        positions_received: list[Position] = []

        @client.on(Event.POSITION)
        def on_position(pos: Position) -> None:
            positions_received.append(pos)

        p_struct = TConnectorTradingAccountPosition()
        p_struct.Version = 0
        p_struct.DailyQuantity = 5
        p_struct.OpenAveragePrice = 5200.0
        p_struct.DailyBuyQuantity = 5
        p_struct.DailySellQuantity = 0
        p_struct.DailyAverageBuyPrice = 5200.0
        p_struct.DailyAverageSellPrice = 0.0
        acc = TConnectorAccountIdentifier()
        acc.Version = 0
        acc.BrokerID = 3
        acc.AccountID = "12345"
        acc.SubAccountID = ""
        acc.Reserved = 0
        p_struct.AccountID = acc

        asset = TConnectorAssetIdentifier()
        asset.Version = 0
        asset.Ticker = "WDOFUT"
        asset.Exchange = "F"
        asset.FeedType = 0
        p_struct.AssetID = asset

        fake_backend.set_mock_position("WDOFUT", "12345", p_struct)

        import time

        with client._dispatcher:
            client._on_asset_position_list(acc, asset, 0)
            time.sleep(0.1)

        assert len(positions_received) == 1
        pos = positions_received[0]
        assert pos.asset.ticker == "WDOFUT"
        assert pos.quantity == 5
        assert pos.average_price == 5200.0
