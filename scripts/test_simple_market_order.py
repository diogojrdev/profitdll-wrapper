#!/usr/bin/env python3
"""Simplified test script for Market Orders (Buy & Sell) on BITFUT / WINFUT.

Displays:
  - ProfitID returned by native DLL
  - Status Transitions (e.g. CLIENT_CREATED -> ORDER_NOT_CREATED)
  - Text Message field (`text_message`) returned by DLL
  - Comprehensive log summary of received order callbacks
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from examples._common import load_env

from profitdll_wrapper import Event, Order, OrderStatus, ProfitClient


class SimpleOrderTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[int, threading.Event] = {}
        self._orders: dict[int, Order] = {}
        self._all_callbacks: list[Order] = []

    def register(self, order_id: int) -> threading.Event:
        with self._lock:
            evt = threading.Event()
            self._events[order_id] = evt
            return evt

    def update(self, order: Order) -> None:
        with self._lock:
            self._all_callbacks.append(order)
            self._orders[order.id] = order
            if (
                order.status
                in (
                    OrderStatus.FILLED,
                    OrderStatus.REJECTED,
                    OrderStatus.CANCELED,
                    OrderStatus.ORDER_NOT_CREATED,
                )
                and order.id in self._events
            ):
                self._events[order.id].set()

    def get_order(self, order_id: int) -> Order | None:
        with self._lock:
            return self._orders.get(order_id)

    def dump_callbacks(self) -> None:
        with self._lock:
            for o in self._all_callbacks:
                cl_ord = getattr(o, "cl_ord_id", "")
                msg = getattr(o, "text_message", "")
                print(
                    f"     - ID=#{o.id} Status={o.status.name} Side={o.side.name} "
                    f"Qty={o.traded_quantity}/{o.quantity} AvgPrice={o.average_price:.2f} "
                    f"ClOrdID={cl_ord} Message='{msg}'"
                )


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
    broker_id = int(broker_id_str) if broker_id_str.isdigit() else 15003

    print("=" * 75)
    print("profitdll-wrapper - MARKET ORDER TEST (BUY + SELL)")
    print("=" * 75)
    print(f"Asset:         {ticker} (Exchange: {exchange})")
    print(f"Account ID:    {account_id}")
    print(f"Broker ID:     {broker_id}")
    print(f"Time:          {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 75)

    tracker = SimpleOrderTracker()

    print("\n[1/4] Instantiating ProfitClient in 'routing' mode...")
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
        msg = getattr(order, "text_message", "")
        print(
            f"   >> [ORDER CALLBACK] ID=#{order.id} | Status={order.status.name} | "
            f"Side={order.side.name} | Qty={order.traded_quantity}/{order.quantity} | "
            f"AvgPrice={order.average_price:.2f} | ClOrdID={cl_ord} | Message='{msg}' | Time={ts}"
        )
        tracker.update(order)

    print("\n[2/4] Connecting to server (Timeout: 30s)...")
    try:
        client.connect(timeout=30.0)
        print("   [OK] Connected and authenticated successfully!")
    except Exception as exc:
        print(f"   [CRITICAL ERROR] Failed to connect: {exc}", file=sys.stderr)
        return 1

    try:
        trade_qty = 1

        print(f"\n[2.5/4] Subscribing to asset {ticker} (Exchange '{exchange}')...")
        client.subscribe(ticker, exchange=exchange)
        client.subscribe_price_depth(ticker, exchange=exchange)
        time.sleep(1.0)
        print("   [OK] Subscribed successfully!")

        # STEP 3: Submitting BUY Market Order
        print(f"\n[3/4] Submitting BUY Market Order ({ticker}, Qty: {trade_qty})...")
        buy_order_id = client.send_market_buy(
            ticker,
            exchange=exchange,
            account=account_id,
            password=routing_key,
            quantity=trade_qty,
            broker_id=broker_id,
        )
        print(f"   [RETURN] ProfitID: #{buy_order_id}")
        if buy_order_id <= 0:
            print(
                f"   [ERROR] ProfitID <= 0 indicates order submission error! Code: {buy_order_id}"
            )
            return 1

        buy_evt = tracker.register(buy_order_id)
        print("   Waiting for BUY order response (Timeout: 15s)...")
        buy_evt.wait(timeout=15.0)

        final_buy = tracker.get_order(buy_order_id)
        final_buy_st = final_buy.status.name if final_buy else "TIMEOUT/NO_CALLBACK"
        final_buy_msg = getattr(final_buy, "text_message", "") if final_buy else ""
        print(f"   [BUY RESULT] Status: {final_buy_st}")
        print(f"   [BUY RESULT] Message: '{final_buy_msg}'")
        if final_buy:
            cl_ord = getattr(final_buy, "cl_ord_id", "")
            print(f"   [BUY RESULT] ClOrdID: {cl_ord}")
            print(
                f"   [BUY RESULT] AvgPrice: {final_buy.average_price:.2f} | Qty: {final_buy.traded_quantity}/{final_buy.quantity}"
            )

        time.sleep(2.0)

        # STEP 4: Submitting SELL Market Order
        print(f"\n[4/4] Submitting SELL Market Order ({ticker}, Qty: {trade_qty}) to ZERO...")
        sell_order_id = client.send_market_sell(
            ticker,
            exchange=exchange,
            account=account_id,
            password=routing_key,
            quantity=trade_qty,
            broker_id=broker_id,
        )
        print(f"   [RETURN] ProfitID: #{sell_order_id}")
        if sell_order_id <= 0:
            print(
                f"   [ERROR] ProfitID <= 0 indicates order submission error! Code: {sell_order_id}"
            )
            return 1

        sell_evt = tracker.register(sell_order_id)
        print("   Waiting for SELL order response (Timeout: 15s)...")
        sell_evt.wait(timeout=15.0)

        final_sell = tracker.get_order(sell_order_id)
        final_sell_st = final_sell.status.name if final_sell else "TIMEOUT/NO_CALLBACK"
        final_sell_msg = getattr(final_sell, "text_message", "") if final_sell else ""
        print(f"   [SELL RESULT] Status: {final_sell_st}")
        print(f"   [SELL RESULT] Message: '{final_sell_msg}'")
        if final_sell:
            cl_ord = getattr(final_sell, "cl_ord_id", "")
            print(f"   [SELL RESULT] ClOrdID: {cl_ord}")
            print(
                f"   [SELL RESULT] AvgPrice: {final_sell.average_price:.2f} | Qty: {final_sell.traded_quantity}/{final_sell.quantity}"
            )

        print("\n" + "=" * 75)
        print("RECEIVED CALLBACKS SUMMARY:")
        tracker.dump_callbacks()
        print("=" * 75)

        success = True
        if final_buy_st == "FILLED":
            print("[OK] BUY: FILLED successfully!")
        else:
            print(
                f"[FAILURE] BUY: Expected FILLED, got {final_buy_st} (Message: '{final_buy_msg}')"
            )
            success = False

        if final_sell_st == "FILLED":
            print("[OK] SELL: FILLED successfully!")
        else:
            print(
                f"[FAILURE] SELL: Expected FILLED, got {final_sell_st} (Message: '{final_sell_msg}')"
            )
            success = False

        if success:
            print("\nTEST COMPLETED SUCCESSFULLY - Market orders operating nominally!")
        else:
            print("\nTEST COMPLETED WITH ISSUES")

        print("=" * 75)
        return 0 if success else 1

    finally:
        print("\nDisconnecting profitdll-wrapper...")
        try:
            client.disconnect()
            print("   [OK] Disconnected.")
        except Exception as e:
            print(f"   [WARNING] Disconnection error: {e}")


if __name__ == "__main__":
    sys.exit(main())
