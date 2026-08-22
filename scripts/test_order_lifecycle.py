"""End-to-End Order Routing, Execution, and Custody Lifecycle Test Script.

Validates the full order lifecycle against Nelogica Simulation Server (Futures Market - WDOFUT/WINFUT, Exchange F):
1. Connection in 'routing' mode with account lockout protection
2. Subscription and capture of offer book depth (Bid / Ask)
3. Submitting buy market order and tracking status transitions to OrderStatus.FILLED
4. Submitting sell market order (position zeroing) and tracking status to OrderStatus.FILLED
5. Verifying zeroed final custody position (quantity == 0 via get_position)
6. Clean disconnection
"""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from examples._common import load_env

from profitdll_wrapper import (
    Event,
    Order,
    OrderStatus,
    Position,
    PriceBookSnapshot,
    PriceLevel,
    ProfitClient,
)


class OrderTracker:
    """Thread-safe manager for tracking order lifecycle state transitions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[int, threading.Event] = {}
        self._orders: dict[int, Order] = {}

    def register(self, order_id: int) -> threading.Event:
        """Registers an order to wait for terminal state (FILLED, CANCELED, REJECTED)."""
        with self._lock:
            evt = threading.Event()
            self._events[order_id] = evt
            target = self._orders.get(order_id)
            if target and target.status in (
                OrderStatus.FILLED,
                OrderStatus.CANCELED,
                OrderStatus.REJECTED,
            ):
                evt.set()
            return evt

    def update(self, order: Order) -> None:
        """Updates internal order state and signals event if terminal state is reached."""
        with self._lock:
            self._orders[order.id] = order
            if (
                order.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED)
                and order.id in self._events
            ):
                self._events[order.id].set()

    def get_order(self, order_id: int) -> Order | None:
        """Returns the latest order snapshot."""
        with self._lock:
            return self._orders.get(order_id)


def main() -> int:
    env = load_env()

    activation_key = env.get("ACTIVATION_KEY", "")
    user = env.get("USER", "")
    password = env.get("PASSWORD", "")
    routing_key = env.get("ROUTING_KEY", "")
    account_id = env.get("ACCOUNT_ID", "")
    broker_id_str = env.get("BROKER", "15003")
    broker_id = int(broker_id_str) if broker_id_str.isdigit() else 15003

    print("=" * 75)
    print("profitdll-wrapper v0.3.0 - END-TO-END ORDER LIFECYCLE & CUSTODY TEST")
    print("=" * 75)
    print(f"User:          {user[:3]}***@{user.split('@')[-1] if '@' in user else '***'}")
    print(f"Account ID:    {account_id}")
    print(f"Broker ID:     {broker_id} (Nelogica Simulator)")
    print(f"Routing Key:   {'[PRESENT]' if routing_key else '[MISSING]'}")
    print(f"Activation Key:{'[PRESENT]' if activation_key else '[MISSING]'}")
    print("=" * 75)

    if not (activation_key and user and password and routing_key and account_id):
        print("CRITICAL ERROR: Incomplete credentials in .env file!", file=sys.stderr)
        print(
            "Please ensure ACTIVATION_KEY, USER, PASSWORD, ROUTING_KEY, and ACCOUNT_ID are configured.",
            file=sys.stderr,
        )
        return 2

    ticker = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TICKER", "WINFUT")
    exchange = "F"
    tracker = OrderTracker()

    best_bid: float | None = None
    best_ask: float | None = None
    book_event = threading.Event()

    print("\n[STEP 1/6] Instantiating ProfitClient in 'routing' mode...")
    client = ProfitClient(
        activation_key=activation_key,
        user=user,
        password=password,
        mode="routing",
    )

    @client.on(Event.ORDER)
    def on_order(order: Order) -> None:
        timestamp_str = order.timestamp.strftime("%H:%M:%S.%f")[:-3] if order.timestamp else "N/A"
        print(
            f"   >> [ORDER STATUS] ID={order.id} | Status={order.status.name} | "
            f"Side={order.side.name} | Traded Qty={order.traded_quantity}/{order.quantity} | "
            f"Price={order.price:.2f} | AvgPrice={order.average_price:.2f} | Time={timestamp_str}"
        )
        tracker.update(order)

    @client.on(Event.POSITION)
    def on_position(pos: Position) -> None:
        print(
            f"   >> [EVENT.POSITION] Asset={pos.asset.ticker} | Account={pos.account_id} | "
            f"Qty={pos.quantity} | AvgPrice={pos.average_price:.2f} | Realized PnL=$ {pos.realized_profit:.2f}"
        )

    @client.on(Event.PRICE_LEVEL)
    def on_price_level(level: PriceLevel) -> None:
        nonlocal best_bid, best_ask
        if level.asset.ticker == ticker and level.price > 0:
            if level.side.name == "BUY" and (best_bid is None or level.position == 0):
                best_bid = level.price
            elif level.side.name == "SELL" and (best_ask is None or level.position == 0):
                best_ask = level.price
            book_event.set()

    @client.on(Event.PRICE_SNAPSHOT)
    def on_price_snapshot(snapshot: PriceBookSnapshot) -> None:
        nonlocal best_bid, best_ask
        if snapshot.asset.ticker == ticker:
            if snapshot.buy_levels:
                best_bid = snapshot.buy_levels[0].price
            if snapshot.sell_levels:
                best_ask = snapshot.sell_levels[0].price
            book_event.set()

    print("\n[STEP 2/6] Connecting to Nelogica server (Timeout: 30s)...")
    try:
        client.connect(timeout=30.0)
        print("   [OK] Order routing connection established successfully!")
    except Exception as exc:
        print(f"\n[CRITICAL AUTHENTICATION / CONNECTION ERROR]: {exc}", file=sys.stderr)
        print("HALTING EXECUTION IMMEDIATELY TO PROTECT ACCOUNT FROM LOCKOUT!", file=sys.stderr)
        return 1

    try:
        print(
            f"\n[STEP 3/6] Subscribing to Ticker and Offer Book for {ticker} (Exchange '{exchange}')..."
        )
        client.subscribe(ticker, exchange=exchange)
        client.subscribe_price_depth(ticker, exchange=exchange)

        print("   Waiting for market Bid/Ask offers...")
        book_event.wait(timeout=10.0)

        from profitdll_wrapper._bindings.enums import BookSide

        try:
            bid_lvl = client.get_price_group(ticker, BookSide.BUY, 0, exchange=exchange)
            if bid_lvl.price > 0:
                best_bid = bid_lvl.price
        except Exception:
            pass

        try:
            ask_lvl = client.get_price_group(ticker, BookSide.SELL, 0, exchange=exchange)
            if ask_lvl.price > 0:
                best_ask = ask_lvl.price
        except Exception:
            pass

        if best_bid is not None or best_ask is not None:
            print(
                f"   [OK] Top of Book for {ticker}: Bid = $ {best_bid or 0:.2f} | Ask = $ {best_ask or 0:.2f}"
            )
        else:
            print(f"   [WARNING] Top of book data not received within 10s for {ticker}.")

        print(f"\n[STEP 4/6] Querying initial custody position for {ticker}...")
        try:
            init_pos = client.get_position(
                ticker, exchange=exchange, account=account_id, broker_id=broker_id
            )
            print(
                f"   [OK] Initial Position: {init_pos.quantity} contracts @ $ {init_pos.average_price:.2f}"
            )
        except Exception as exc:
            print(f"   [WARNING] Initial get_position: {exc}")

        trade_qty = 1
        print(f"\n[STEP 5/6 - PART A] Submitting BUY Market Order (Qty: {trade_qty})...")
        buy_order_id = client.send_market_buy(
            ticker,
            exchange=exchange,
            account=account_id,
            password=routing_key,
            quantity=trade_qty,
            broker_id=broker_id,
        )

        print(f"   [OK] BUY Order accepted by DLL! OrderID / ProfitID: #{buy_order_id}")

        buy_evt = tracker.register(buy_order_id)
        print("   Waiting for BUY order execution confirmation (FILLED) (Timeout: 15s)...")
        filled_buy = buy_evt.wait(timeout=15.0)

        buy_order_final = tracker.get_order(buy_order_id)
        if not filled_buy or (buy_order_final and buy_order_final.status != OrderStatus.FILLED):
            final_st = buy_order_final.status.name if buy_order_final else "UNKNOWN"
            print(
                f"   [ERROR] BUY Order #{buy_order_id} did not finish as FILLED! Final Status: {final_st}",
                file=sys.stderr,
            )
            return 1

        print(
            f"   [SUCCESS] BUY Order #{buy_order_id} EXECUTED! Average Price: $ {buy_order_final.average_price:.2f}"
        )

        time.sleep(1.0)

        print(
            f"\n[STEP 5/6 - PART B] Submitting SELL Market Order to Zero Position (Qty: {trade_qty})..."
        )
        sell_order_id = client.send_market_sell(
            ticker,
            exchange=exchange,
            account=account_id,
            password=routing_key,
            quantity=trade_qty,
            broker_id=broker_id,
        )

        print(f"   [OK] SELL Order accepted by DLL! OrderID / ProfitID: #{sell_order_id}")

        sell_evt = tracker.register(sell_order_id)
        print("   Waiting for SELL order execution confirmation (FILLED) (Timeout: 15s)...")
        filled_sell = sell_evt.wait(timeout=15.0)

        sell_order_final = tracker.get_order(sell_order_id)
        if not filled_sell or (sell_order_final and sell_order_final.status != OrderStatus.FILLED):
            final_st = sell_order_final.status.name if sell_order_final else "UNKNOWN"
            print(
                f"   [ERROR] SELL Order #{sell_order_id} did not finish as FILLED! Final Status: {final_st}",
                file=sys.stderr,
            )
            return 1

        print(
            f"   [SUCCESS] SELL Order #{sell_order_id} EXECUTED! Average Price: $ {sell_order_final.average_price:.2f}"
        )

        time.sleep(1.0)

        print("\n[STEP 6/6] Verifying Final Custody via get_position...")
        final_pos = client.get_position(
            ticker, exchange=exchange, account=account_id, broker_id=broker_id
        )
        print(
            f"   >> Final Custody Position: Quantity={final_pos.quantity} | "
            f"Day Buy={final_pos.buy_quantity} | Day Sell={final_pos.sell_quantity}"
        )

        if final_pos.quantity == 0:
            print("\n" + "=" * 75)
            print(
                "   [VALIDATION SUCCESS]: FINAL CUSTODY POSITION IS COMPLETELY ZEROED (quantity == 0)!"
            )
            print("=" * 75)
        else:
            print(
                f"\n[CUSTODY FAILURE]: Expected quantity == 0, but final position was {final_pos.quantity}!",
                file=sys.stderr,
            )
            return 1

    except Exception as exc:
        print(f"\n[ERROR DURING ROUTING WORKFLOW]: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        print("\n[TEARDOWN] Disconnecting profitdll-wrapper...")
        client.disconnect()
        print("   [OK] Disconnected successfully.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
