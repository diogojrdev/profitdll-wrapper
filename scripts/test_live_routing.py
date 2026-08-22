"""Live order routing verification script for profitdll-wrapper (Futures Market).

Executes against native ProfitDLL and Nelogica simulation server.
In case of connection failure on 1st attempt, halts immediately to protect account.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from examples._common import load_env

from profitdll_wrapper import Event, Order, Position, ProfitClient


def main() -> int:
    env = load_env()

    activation_key = env.get("ACTIVATION_KEY", "")
    user = env.get("USER", "")
    password = env.get("PASSWORD", "")
    routing_key = env.get("ROUTING_KEY", "")
    account_id = env.get("ACCOUNT_ID", "")
    broker_id_str = env.get("BROKER", "15003")
    broker_id = int(broker_id_str) if broker_id_str.isdigit() else 15003

    print("=" * 60)
    print("profitdll-wrapper - LIVE ORDER ROUTING TEST (FUTURES MARKET)")
    print("=" * 60)
    print(f"User:          {user[:3]}***@{user.split('@')[-1] if '@' in user else '***'}")
    print(f"Account:       {account_id}")
    print(f"Broker ID:     {broker_id}")
    print(f"Routing Key:   {'[PRESENT]' if routing_key else '[MISSING]'}")
    print(f"Activation Key:{'[PRESENT]' if activation_key else '[MISSING]'}")
    print("=" * 60)

    if not (activation_key and user and password and routing_key and account_id):
        print("ERROR: Incomplete credentials in .env file!", file=sys.stderr)
        print(
            "Please ensure ACTIVATION_KEY, USER, PASSWORD, ROUTING_KEY, and ACCOUNT_ID are defined.",
            file=sys.stderr,
        )
        return 2

    ticker = "WDOFUT"
    exchange = "F"  # BMF / Futures Market

    print("\n[1/5] Connecting to server in 'routing' mode (Timeout: 30s)...")
    client = ProfitClient(
        activation_key=activation_key,
        user=user,
        password=password,
        mode="routing",
    )

    orders_received: list[Order] = []
    positions_received: list[Position] = []

    @client.on(Event.ORDER)
    def on_order(order: Order) -> None:
        orders_received.append(order)
        print(
            f"   >> [EVENT.ORDER] ProfitID={order.id} | Asset={order.asset.ticker} | "
            f"Side={order.side.name} | Status={order.status.name} | "
            f"Price={order.price:.2f} | Executed={order.traded_quantity}/{order.quantity}"
        )

    @client.on(Event.POSITION)
    def on_position(pos: Position) -> None:
        positions_received.append(pos)
        print(
            f"   >> [EVENT.POSITION] Asset={pos.asset.ticker} | Account={pos.account_id} | "
            f"Qty={pos.quantity} | AvgPrice={pos.average_price:.2f}"
        )

    try:
        client.connect(timeout=30.0)
        print("   [OK] Order routing connection and authentication established successfully!")
    except Exception as exc:
        print(f"\n[CRITICAL CONNECTION ERROR]: {exc}", file=sys.stderr)
        print("HALTING EXECUTION IMMEDIATELY TO PROTECT ACCOUNT FROM LOCKOUT!", file=sys.stderr)
        return 1

    try:
        # 2. Query initial position in WDOFUT
        print(f"\n[2/5] Querying initial position for {ticker} (Exchange {exchange})...")
        try:
            pos = client.get_position(
                ticker, exchange=exchange, account=account_id, broker_id=broker_id
            )
            print(
                f"   [OK] Current position in {ticker}: {pos.quantity} contracts @ $ {pos.average_price:.2f}"
            )
        except Exception as exc:
            print(f"   [WARNING] get_position returned: {exc}")

        # 3. Submit limit buy order (safe test price far below market)
        test_price = 4000.0
        test_qty = 1
        print("\n[3/5] Submitting test limit buy order:")
        print(
            f"   Asset: {ticker} | Price: $ {test_price:.2f} | Qty: {test_qty} | Account: {account_id}"
        )

        order_id = client.send_buy_order(
            ticker,
            exchange=exchange,
            account=account_id,
            password=routing_key,
            price=test_price,
            quantity=test_qty,
            broker_id=broker_id,
        )
        print(f"   [OK] Order accepted by DLL! OrderID / ProfitID generated: #{order_id}")

        time.sleep(2.0)

        # 4. Cancel test order
        print(f"\n[4/5] Cancelling limit order #{order_id}...")
        client.cancel_order(
            account_id,
            order_id,
            password=routing_key,
            broker_id=broker_id,
        )
        print("   [OK] Cancellation request submitted.")

        time.sleep(2.0)

        # 5. Summary
        print("\n[5/5] Received Events Summary:")
        print(f"   Total order events received: {len(orders_received)}")
        print(f"   Total position events received: {len(positions_received)}")
        print("\n" + "=" * 60)
        print("LIVE ORDER ROUTING TEST COMPLETED SUCCESSFULLY!")
        print("=" * 60)

    except Exception as exc:
        print(f"\n[ERROR DURING ORDER EXECUTION/CANCELLATION]: {exc}", file=sys.stderr)
        return 1
    finally:
        print("\nClosing connection with profitdll-wrapper...")
        client.disconnect()
        print("Disconnected successfully.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
