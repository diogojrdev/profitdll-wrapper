"""Order routing and real-time position management example (Routing Mode).

Demonstrates limit/market order placement, order cancellations, and monitoring
order execution events (`Event.ORDER`) and position updates (`Event.POSITION`).

Prerequisites:
  * Windows 64-bit OS with Python 64-bit;
  * ProfitDLL binary available (defined via PROFITDLL_PATH env var or inside `dll/`);
  * Credentials set in `.env` file or environment variables.

Execution:

    uv run python examples/04_send_order.py
"""

from __future__ import annotations

import sys
import threading

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import (
    Event,
    Order,
    Position,
    ProfitClient,
)


def main() -> int:
    setup_dll_path()
    activation_key, user, password, account = load_credentials()

    if not (activation_key and user and password):
        print(
            "Missing credentials. Please define PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, "
            "and PROFITDLL_PASSWORD in your .env file or environment.",
            file=sys.stderr,
        )
        return 2

    ticker = "WDOFUT"
    exchange = "F"  # BMF (Derivatives)

    try:
        with ProfitClient(
            activation_key=activation_key,
            user=user,
            password=password,
            mode="routing",  # Enables full order routing mode
        ) as client:
            print(f"Connected to routing mode. Account: {account}")

            @client.on(Event.ORDER)
            def on_order(order: Order) -> None:
                print(
                    f"[ORDER] ID={order.id} | Asset={order.asset.ticker} | "
                    f"Side={order.side.name} | Status={order.status.name} | "
                    f"Executed: {order.traded_quantity}/{order.quantity} @ {order.price:.2f}"
                )

            @client.on(Event.POSITION)
            def on_position(pos: Position) -> None:
                print(
                    f"[POSITION] Asset={pos.asset.ticker} | Qty: {pos.quantity} | "
                    f"Avg Price: {pos.average_price:.2f}"
                )

            # 1. Query initial position
            try:
                pos = client.get_position(ticker, exchange=exchange, account=account)
                print(f"Initial custody position for {ticker}: {pos.quantity} contracts @ {pos.average_price:.2f}")
            except Exception as exc:
                print(f"Could not query initial custody position: {exc}")

            # 2. Submit test limit buy order (far below market price for safe testing)
            print(f"Submitting test limit buy order for {ticker}...")
            order_id = client.send_buy_order(
                ticker,
                exchange=exchange,
                account=account,
                password=password,
                price=4000.0,  # Safe test price far below market
                quantity=1,
            )
            print(f"Order successfully placed! ProfitID: {order_id}")

            # 3. Cancel test order
            print(f"Cancelling order #{order_id}...")
            client.cancel_order(account, order_id, password=password)
            print("Cancellation request submitted successfully.")

            print("Processing events for 5 seconds (Press Ctrl+C to exit)...")
            timer = threading.Timer(5.0, client.stop)
            timer.start()
            try:
                client.run()
            finally:
                timer.cancel()
    except KeyboardInterrupt:
        print("\nDisconnecting and exiting.")
    except Exception as exc:
        print(f"Error executing order routing example: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
