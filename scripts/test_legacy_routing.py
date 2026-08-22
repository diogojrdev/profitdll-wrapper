#!/usr/bin/env python3
"""Legacy order routing test script (SendMarketBuyOrder / SendMarketSellOrder).

Verifies whether legacy C function calls work against the Nelogica simulator environment.
"""

from __future__ import annotations

import os
import sys
import time
from ctypes import c_int, c_int64, c_wchar_p

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from examples._common import load_env

from profitdll_wrapper import Event, Order, ProfitClient


def main() -> int:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "BITFUT"
    exchange = "F"

    env = load_env()
    activation_key = env.get("ACTIVATION_KEY", "")
    user = env.get("USER", "")
    password = env.get("PASSWORD", "")
    routing_key = env.get("ROUTING_KEY", "")
    account_id = env.get("ACCOUNT_ID", "")
    broker_id_str = env.get("BROKER", "15003")

    print("=" * 75)
    print("LEGACY ORDER ROUTING TEST (SendMarketBuyOrder / SendMarketSellOrder)")
    print("=" * 75)
    print(f"Asset: {ticker} | Account: {account_id} | Broker: {broker_id_str}")
    print("=" * 75)

    client = ProfitClient(
        activation_key=activation_key,
        user=user,
        password=password,
        mode="routing",
    )

    @client.on(Event.ORDER)
    def on_order(order: Order) -> None:
        cl_ord = getattr(order, "cl_ord_id", "")
        print(
            f"   >> [ORDER CALLBACK] ID=#{order.id} Status={order.status.name} "
            f"Side={order.side.name} Qty={order.traded_quantity}/{order.quantity} "
            f"AvgPrice={order.average_price:.2f} ClOrdID={cl_ord}"
        )

    print("\nConnecting...")
    client.connect(timeout=30.0)
    print("Connected successfully!")

    dll = client._backend._lib

    fn_mkt_buy = dll.SendMarketBuyOrder
    fn_mkt_buy.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_int]
    fn_mkt_buy.restype = c_int64

    fn_mkt_sell = dll.SendMarketSellOrder
    fn_mkt_sell.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_int]
    fn_mkt_sell.restype = c_int64

    print(f"\n[1] Submitting SendMarketBuyOrder for {ticker}...")
    pid1 = fn_mkt_buy(
        c_wchar_p(account_id),
        c_wchar_p(broker_id_str),
        c_wchar_p(routing_key),
        c_wchar_p(ticker),
        c_wchar_p(exchange),
        c_int(1),
    )
    print(f"   Returned ProfitID: {pid1}")

    time.sleep(5.0)

    print(f"\n[2] Submitting SendMarketSellOrder for {ticker} (position zeroing)...")
    pid2 = fn_mkt_sell(
        c_wchar_p(account_id),
        c_wchar_p(broker_id_str),
        c_wchar_p(routing_key),
        c_wchar_p(ticker),
        c_wchar_p(exchange),
        c_int(1),
    )
    print(f"   Returned ProfitID: {pid2}")

    time.sleep(5.0)

    print("\nDisconnecting...")
    client.disconnect()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
