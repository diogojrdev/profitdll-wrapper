#!/usr/bin/env python3
"""Comparative parameter diagnostic script for BITFUT:

1. SendMarketBuyOrder (legacy market order)
2. SendBuyOrder (legacy limit order)
3. SendOrder (v2 struct limit order)
"""

from __future__ import annotations

import os
import sys
import time
from ctypes import c_double, c_int, c_int64, c_wchar_p

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from examples._common import load_env

from profitdll_wrapper import Event, Order, ProfitClient


def main() -> int:
    ticker = "BITFUT"
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
    print("BITFUT PARAMETER AND MESSAGE DIAGNOSTIC")
    print("=" * 75)

    client = ProfitClient(
        activation_key=activation_key,
        user=user,
        password=password,
        mode="routing",
    )

    @client.on(Event.ORDER)
    def on_order(order: Order) -> None:
        ts = order.timestamp.strftime("%H:%M:%S.%f")[:-3] if order.timestamp else "N/A"
        msg = getattr(order, "text_message", "")
        print(
            f"   >> [CALLBACK] ID=#{order.id} Status={order.status.name} "
            f"Side={order.side.name} Qty={order.traded_quantity}/{order.quantity} "
            f"Price={order.price:.2f} AvgPrice={order.average_price:.2f} Message='{msg}' Time={ts}"
        )

    print("\nConnecting...")
    client.connect(timeout=30.0)
    print("Connected!")

    dll = client._backend._lib

    # 1. Configure C signatures
    dll.SendMarketBuyOrder.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_int]
    dll.SendMarketBuyOrder.restype = c_int64

    dll.SendBuyOrder.argtypes = [
        c_wchar_p,
        c_wchar_p,
        c_wchar_p,
        c_wchar_p,
        c_wchar_p,
        c_double,
        c_int,
    ]
    dll.SendBuyOrder.restype = c_int64

    # TEST 1: SendMarketBuyOrder (legacy)
    print("\n[TEST 1] SendMarketBuyOrder (legacy market buy)...")
    pid1 = dll.SendMarketBuyOrder(
        c_wchar_p(account_id),
        c_wchar_p(broker_id_str),
        c_wchar_p(routing_key),
        c_wchar_p(ticker),
        c_wchar_p(exchange),
        c_int(1),
    )
    print(f"   ProfitID returned: {pid1}")
    time.sleep(4.0)

    # TEST 2: SendBuyOrder (legacy limit buy)
    limit_price = 600000.00
    print(f"\n[TEST 2] SendBuyOrder (legacy limit buy @ $ {limit_price:.2f})...")
    pid2 = dll.SendBuyOrder(
        c_wchar_p(account_id),
        c_wchar_p(broker_id_str),
        c_wchar_p(routing_key),
        c_wchar_p(ticker),
        c_wchar_p(exchange),
        c_double(limit_price),
        c_int(1),
    )
    print(f"   ProfitID returned: {pid2}")
    time.sleep(4.0)

    # TEST 3: SendOrder (struct limit via ProfitClient)
    print(f"\n[TEST 3] client.send_buy_order (struct limit buy @ $ {limit_price:.2f})...")
    pid3 = client.send_buy_order(
        ticker,
        exchange=exchange,
        account=account_id,
        password=routing_key,
        price=limit_price,
        quantity=1,
        broker_id=broker_id,
    )
    print(f"   ProfitID returned: {pid3}")
    time.sleep(4.0)

    print("\nDisconnecting...")
    client.disconnect()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
