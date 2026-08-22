#!/usr/bin/env python3
"""Diagnostic script comparing order submission via SendOrder (V2 struct) vs
SendMarketBuyOrder (legacy function).

Objective: Determine whether order routing issues stem from TConnectorSendOrder layout
or account/broker configuration.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import byref, c_int, c_int64, c_wchar_p
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from examples._common import load_env

from profitdll_wrapper import Event, Order, OrderStatus, ProfitClient


class OrderCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[int, threading.Event] = {}
        self._orders: dict[int, list[Order]] = {}

    def register(self, order_id: int) -> threading.Event:
        with self._lock:
            evt = threading.Event()
            self._events[order_id] = evt
            self._orders.setdefault(order_id, [])
            return evt

    def update(self, order: Order) -> None:
        with self._lock:
            self._orders.setdefault(order.id, []).append(order)
            if (
                order.status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED)
                and order.id in self._events
            ):
                self._events[order.id].set()

    def get_latest(self, order_id: int) -> Order | None:
        with self._lock:
            history = self._orders.get(order_id, [])
            return history[-1] if history else None

    def get_all(self, order_id: int) -> list[Order]:
        with self._lock:
            return list(self._orders.get(order_id, []))


def main() -> int:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "WINFUT"
    exchange = "F"

    env = load_env()
    activation_key = env.get("ACTIVATION_KEY", "")
    user = env.get("USER", "")
    password = env.get("PASSWORD", "")
    routing_key = env.get("ROUTING_KEY", "")
    account_id = env.get("ACCOUNT_ID", "")
    broker_id_str = env.get("BROKER", "15003")
    broker_id = int(broker_id_str) if broker_id_str.isdigit() else 15003

    print("=" * 75)
    print("DIAGNOSTIC: SendOrder (struct) vs SendMarketBuyOrder (legacy)")
    print("=" * 75)
    print(f"Asset:         {ticker} (Exchange: {exchange})")
    print(f"Account ID:    {account_id}")
    print(f"Broker ID:     {broker_id} (string: '{broker_id_str}')")
    print(f"Routing Key:   {'*' * len(routing_key)} ({len(routing_key)} chars)")
    print(f"Time:          {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 75)

    collector = OrderCollector()

    print("\n[1/5] Instantiating ProfitClient in 'routing' mode...")
    client = ProfitClient(
        activation_key=activation_key,
        user=user,
        password=password,
        mode="routing",
    )

    @client.on(Event.ORDER)
    def on_order(order: Order) -> None:
        ts = order.timestamp.strftime("%H:%M:%S.%f")[:-3] if order.timestamp else "N/A"
        cl_ord = getattr(order, "cl_ord_id", "")
        print(
            f"   >> [CALLBACK] ID=#{order.id} | Status={order.status.name} | "
            f"Side={order.side.name} | Qty={order.traded_quantity}/{order.quantity} | "
            f"AvgPrice={order.average_price:.2f} | ClOrdID={cl_ord} | Time={ts}"
        )
        collector.update(order)

    print("\n[2/5] Connecting to server (Timeout: 30s)...")
    try:
        client.connect(timeout=30.0)
        print("   [OK] Connected!")
    except Exception as exc:
        print(f"   [ERROR] Connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        dll = client._backend._lib

        # TEST A: Legacy SendMarketBuyOrder
        print("\n" + "=" * 75)
        print("TEST A: SendMarketBuyOrder (legacy function)")
        print("=" * 75)

        fn_legacy = getattr(dll, "SendMarketBuyOrder", None)
        if fn_legacy is None:
            print("   [ERROR] SendMarketBuyOrder function not found in DLL!")
        else:
            fn_legacy.argtypes = [
                c_wchar_p,  # pwcIDAccount
                c_wchar_p,  # pwcIDCorretora (broker string)
                c_wchar_p,  # pwcSenha (routing key)
                c_wchar_p,  # pwcTicker
                c_wchar_p,  # pwcBolsa
                c_int,  # nAmount
            ]
            fn_legacy.restype = c_int64

            print(
                f"   Params: account='{account_id}', broker='{broker_id_str}', "
                f"pwd=***, ticker='{ticker}', exchange='{exchange}', qty=1"
            )

            profit_id_legacy = fn_legacy(
                c_wchar_p(account_id),
                c_wchar_p(broker_id_str),
                c_wchar_p(routing_key),
                c_wchar_p(ticker),
                c_wchar_p(exchange),
                c_int(1),
            )
            profit_id_legacy = int(profit_id_legacy)
            print(f"   [RETURN] ProfitID (legacy): {profit_id_legacy}")

            if profit_id_legacy > 0:
                evt_a = collector.register(profit_id_legacy)
                print("   Waiting for callbacks (15s)...")
                evt_a.wait(timeout=15.0)
                final_a = collector.get_latest(profit_id_legacy)
                if final_a:
                    cl_a = getattr(final_a, "cl_ord_id", "")
                    print(f"   [RESULT A] Status={final_a.status.name} ClOrdID={cl_a}")
                else:
                    print("   [RESULT A] No callbacks received!")
            else:
                print(f"   [ERROR A] Negative ProfitID error code: {profit_id_legacy}")

        time.sleep(3.0)

        # TEST B: SendOrder (V2 struct)
        print("\n" + "=" * 75)
        print("TEST B: SendOrder (struct TConnectorSendOrder)")
        print("=" * 75)

        from profitdll_wrapper._bindings.enums import OrderSide, OrderType
        from profitdll_wrapper._bindings.structures import TConnectorSendOrder

        order = TConnectorSendOrder()
        order.Version = 1
        order.AccountID.Version = 0
        order.AccountID.BrokerID = broker_id
        order.AccountID.AccountID = account_id
        order.AccountID.SubAccountID = ""
        order.AccountID.Reserved = 0

        order.AssetID.Version = 0
        order.AssetID.Ticker = ticker
        order.AssetID.Exchange = exchange
        order.AssetID.FeedType = 0

        order.Password = routing_key
        order.OrderType = int(OrderType.MARKET)
        order.OrderSide = int(OrderSide.SELL)
        order.Price = 0.0
        order.StopPrice = 0.0
        order.Quantity = 1
        order.MessageID = -1

        _refs = [account_id, ticker, exchange, routing_key, ""]

        print(
            f"   Struct: Version={order.Version}, OrderType={order.OrderType} (MARKET=1), "
            f"OrderSide={order.OrderSide} (SELL=2)"
        )
        print(
            f"   AccountID: BrokerID={order.AccountID.BrokerID}, "
            f"AccountID='{order.AccountID.AccountID}'"
        )
        print(f"   AssetID: Ticker='{order.AssetID.Ticker}', Exchange='{order.AssetID.Exchange}'")

        fn_new = getattr(dll, "SendOrder", None)
        if fn_new is None:
            print("   [ERROR] SendOrder function not found in DLL!")
        else:
            fn_new.argtypes = [ctypes.POINTER(TConnectorSendOrder)]
            fn_new.restype = c_int64

            res = fn_new(byref(order))
            profit_id_new = int(res)
            print(f"   [RETURN] ProfitID (struct): {profit_id_new}")

            if profit_id_new > 0:
                evt_b = collector.register(profit_id_new)
                print("   Waiting for callbacks (15s)...")
                evt_b.wait(timeout=15.0)
                final_b = collector.get_latest(profit_id_new)
                if final_b:
                    cl_b = getattr(final_b, "cl_ord_id", "")
                    print(f"   [RESULT B] Status={final_b.status.name} ClOrdID={cl_b}")
                else:
                    print("   [RESULT B] No callbacks received!")
            else:
                print(f"   [ERROR B] Negative ProfitID error code: {profit_id_new}")

        print("\n" + "=" * 75)
        print("DIAGNOSTIC SUMMARY")
        print("=" * 75)
        print("If TEST A works but TEST B fails:")
        print("  -> Issue is in TConnectorSendOrder struct layout or encoding")
        print("If BOTH fail:")
        print("  -> Account / Broker configuration or simulation environment issue")
        print("If BOTH succeed:")
        print("  -> Order routing is operating nominally")
        print("=" * 75)
        return 0

    finally:
        print("\nDisconnecting...")
        try:
            client.disconnect()
            print("   [OK] Disconnected.")
        except Exception as e:
            print(f"   [WARNING] {e}")


if __name__ == "__main__":
    sys.exit(main())
