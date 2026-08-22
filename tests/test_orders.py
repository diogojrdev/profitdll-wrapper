"""Testes unitários para envio, cancelamento e eventos de ordens (Fase P2)."""

from __future__ import annotations

import pytest

from profitdll_wrapper import Event, Order, OrderSide, OrderStatus, ProfitClient
from profitdll_wrapper._bindings.enums import ROUTING_STATES
from tests.fakes.backend import FakeProfitBackend


class TestOrderRouting:
    def test_send_buy_order_success(self, fake_backend: FakeProfitBackend) -> None:
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

        order_id = client.send_buy_order(
            "WDOFUT",
            exchange="F",
            account="12345",
            password="pwd",
            price=5200.0,
            quantity=2,
        )

        assert order_id > 0
        assert len(fake_backend.orders_sent) == 1
        assert fake_backend.orders_sent[0] == ("WDOFUT", int(OrderSide.BUY), 5200.0, 2)

    def test_send_sell_order_success(self, fake_backend: FakeProfitBackend) -> None:
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

        order_id = client.send_sell_order(
            "PETR4",
            exchange="B",
            account="12345",
            password="pwd",
            price=38.50,
            quantity=100,
        )

        assert order_id > 0
        assert len(fake_backend.orders_sent) == 1
        assert fake_backend.orders_sent[0] == ("PETR4", int(OrderSide.SELL), 38.50, 100)

    def test_send_market_buy_and_sell(self, fake_backend: FakeProfitBackend) -> None:
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

        id1 = client.send_market_buy(
            "WDOFUT", exchange="F", account="12345", password="pwd", quantity=1
        )
        id2 = client.send_market_sell(
            "WDOFUT", exchange="F", account="12345", password="pwd", quantity=1
        )

        assert id1 > 0
        assert id2 > 0
        assert len(fake_backend.orders_sent) == 2

    def test_send_order_invalid_args(self, fake_backend: FakeProfitBackend) -> None:
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

        with pytest.raises(ValueError, match="Unknown exchange 'X_INVALID'"):
            client.send_buy_order(
                "PETR4",
                exchange="X_INVALID",
                account="12345",
                password="pwd",
                price=10.0,
                quantity=1,
            )

        with pytest.raises(ValueError, match="quantity must be > 0"):
            client.send_buy_order(
                "PETR4", exchange="B", account="12345", password="pwd", price=10.0, quantity=0
            )

        with pytest.raises(ValueError, match=r"price must be > 0\.0"):
            client.send_buy_order(
                "PETR4", exchange="B", account="12345", password="pwd", price=0.0, quantity=10
            )

    def test_cancel_order(self, fake_backend: FakeProfitBackend) -> None:
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

        client.cancel_order("12345", 1001, password="pwd")
        assert fake_backend.cancelled_orders == [1001]

    def test_cancel_all_orders(self, fake_backend: FakeProfitBackend) -> None:
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

        client.cancel_all_orders("12345", "WDOFUT", exchange="F", password="pwd")
        assert fake_backend.cancelled_all_ticker == [("WDOFUT", "F")]

    def test_cancel_all_account_orders(self, fake_backend: FakeProfitBackend) -> None:
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

        client.cancel_all_account_orders("12345", password="pwd")
        assert fake_backend.cancelled_all_account == ["12345"]

    def test_change_order_success(self, fake_backend: FakeProfitBackend) -> None:
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

        client.change_order(
            "12345", 1001, price=5250.0, quantity=3, password="pwd", stop_price=5100.0
        )
        assert fake_backend.changed_orders == [(1001, 5250.0, 5100.0, 3)]

    def test_change_order_invalid_args(self, fake_backend: FakeProfitBackend) -> None:
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

        with pytest.raises(ValueError, match="quantity must be > 0"):
            client.change_order("12345", 1001, price=5250.0, quantity=0, password="pwd")

        with pytest.raises(ValueError, match="price cannot be negative"):
            client.change_order("12345", 1001, price=-1.0, quantity=1, password="pwd")

        with pytest.raises(ValueError, match="stop_price cannot be negative"):
            client.change_order(
                "12345", 1001, price=10.0, quantity=1, password="pwd", stop_price=-5.0
            )

    def test_zero_position_market_success(self, fake_backend: FakeProfitBackend) -> None:
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

        order_id = client.zero_position("PETR4", exchange="B", account="12345", password="pwd")
        assert order_id > 0
        assert fake_backend.zeroed_positions == [("PETR4", "B", "12345", -1.0, 0)]

    def test_zero_position_limit_price(self, fake_backend: FakeProfitBackend) -> None:
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

        order_id = client.zero_position(
            "WDOFUT", exchange="F", account="12345", password="pwd", price=5200.0, position_type=1
        )
        assert order_id > 0
        assert fake_backend.zeroed_positions == [("WDOFUT", "F", "12345", 5200.0, 1)]

    def test_zero_position_invalid_exchange(self, fake_backend: FakeProfitBackend) -> None:
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

        with pytest.raises(ValueError, match="Unknown exchange 'INVALID'"):
            client.zero_position("PETR4", exchange="INVALID", account="12345", password="pwd")

    def test_order_event_received(self, fake_backend: FakeProfitBackend) -> None:
        from profitdll_wrapper._bindings.structures import (
            TConnectorAccountIdentifierOut,
            TConnectorAssetIdentifierOut,
            TConnectorOrderIdentifier,
            TConnectorOrderOut,
        )

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

        orders_received: list[Order] = []

        @client.on(Event.ORDER)
        def on_order(ord: Order) -> None:
            orders_received.append(ord)

        with client._dispatcher:
            order_id = TConnectorOrderIdentifier(
                Version=0,
                LocalOrderID=999,
                ClOrderID="CL123",
            )

            mock_details = TConnectorOrderOut(
                Version=0,
                OrderID=order_id,
                AccountID=TConnectorAccountIdentifierOut(
                    Version=0, BrokerID=15003, AccountID="12345"
                ),
                AssetID=TConnectorAssetIdentifierOut(
                    Version=0,
                    Ticker="WDOFUT",
                    TickerLength=6,
                    Exchange="F",
                    ExchangeLength=1,
                ),
                Quantity=5,
                TradedQuantity=5,
                LeavesQuantity=0,
                Price=5200.0,
                StopPrice=0.0,
                AveragePrice=5200.0,
                OrderSide=1,  # Buy
                OrderType=2,  # Limit
                OrderStatus=2,  # Filled
                ValidityType=0,
            )

            fake_backend.set_mock_order_details(999, mock_details)
            fake_backend.emit_order_callback(order_id)

            import time

            time.sleep(0.1)

        assert len(orders_received) == 1
        o = orders_received[0]
        assert o.id == 999
        assert o.asset.ticker == "WDOFUT"
        assert o.side == OrderSide.BUY
        assert o.status == OrderStatus.FILLED
        assert o.quantity == 5
        assert o.traded_quantity == 5

    def test_trading_message_result_event(self, fake_backend: FakeProfitBackend) -> None:
        from profitdll_wrapper._bindings.structures import TConnectorTradingMessageResult
        from profitdll_wrapper._types.models import TradingMessageResult

        fake_backend.connect_states = ROUTING_STATES
        client = ProfitClient(
            activation_key="key",
            user="user",
            password="pass",
            mode="routing",
            backend=fake_backend,
            broker_id=150,
        )

        messages_received: list[TradingMessageResult] = []

        @client.on(Event.TRADING_MESSAGE)
        def _on_msg(msg: TradingMessageResult) -> None:
            messages_received.append(msg)

        client.connect()

        res = TConnectorTradingMessageResult()
        res.Version = 0
        res.BrokerID = 120
        res.OrderID.LocalOrderID = 888
        res.OrderID.ClOrderID = "CL888"
        res.MessageID = 555
        res.ResultCode = 3
        res.Message = "Falta de margem de garantia"
        res.MessageLength = len("Falta de margem de garantia")

        fake_backend.emit_trading_message(res)

        import time

        time.sleep(0.1)

        assert len(messages_received) == 1
        m = messages_received[0]
        assert m.broker_id == 120
        assert m.local_order_id == 888
        assert m.cl_ord_id == "CL888"
        assert m.message_id == 555
        assert m.result_code == 3
        assert m.message == "Falta de margem de garantia"
