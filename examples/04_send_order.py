"""Order routing and real-time position management example (Routing Mode).

Demonstrates limit/market order placement, order cancellations, and monitoring
order execution events (`Event.ORDER`), routing acknowledgements
(`Event.TRADING_MESSAGE`) and position updates (`Event.POSITION`).

Prerequisites:
  * Windows 64-bit OS with Python 64-bit;
  * ProfitDLL binary available (defined via PROFITDLL_PATH env var or inside `dll/`);
  * Credentials set in `.env` file or environment variables — including
    `ROUTING_KEY`, the routing password (distinct from the login password;
    the order server validates it on every order).

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
    TradingMessageResult,
    TradingMessageResultCode,
)


def mrc_name(code: int) -> str:
    """Best-effort name for a TConnectorTradingMessageResultCode value."""
    try:
        return TradingMessageResultCode(code).name
    except ValueError:
        return f"UNKNOWN ({code})"


def main() -> int:
    setup_dll_path()
    activation_key, user, password, account, routing_key = load_credentials()

    if not (activation_key and user and password):
        print(
            "Missing credentials. Please define PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, "
            "and PROFITDLL_PASSWORD in your .env file or environment.",
            file=sys.stderr,
        )
        return 2
    if not routing_key:
        print(
            "Missing ROUTING_KEY: the routing password is required for order placement "
            "and differs from the login password.",
            file=sys.stderr,
        )
        return 2

    ticker = "PETR4"
    exchange = "B"  # Bovespa (B3 equities)

    try:
        with ProfitClient(
            activation_key=activation_key,
            user=user,
            password=password,
            routing_password=routing_key,
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

            @client.on(Event.TRADING_MESSAGE)
            def on_trading_message(msg: TradingMessageResult) -> None:
                # Canonical acceptance chain: 2 -> 4 -> 6 -> 8 -> 10
                # (mrcSentToHadesProxy -> mrcSentToHades -> mrcSentToBroker ->
                #  mrcSentToMarket -> mrcAccepted). If the chain stalls after
                # mrcSentToHades (4), the order server dropped the order —
                # usually an invalid routing password. Do NOT retry blindly.
                print(
                    f"[TM] order={msg.local_order_id} code={msg.result_code} "
                    f"({mrc_name(msg.result_code)}) msg='{msg.message}'"
                )

            @client.on(Event.POSITION)
            def on_position(pos: Position) -> None:
                print(
                    f"[POSITION] Asset={pos.asset.ticker} | Qty: {pos.quantity} | "
                    f"Avg Price: {pos.average_price:.2f}"
                )

            # 0. Validate the target account against the roster reported by the
            # DLL (one login may carry several accounts/brokers).
            roster = client.get_accounts()
            print(f"Account roster reported by DLL ({len(roster)}):")
            for acc in roster:
                print(f"  -> id={acc.account_id} broker={acc.broker_id}")
            if not any(acc.account_id == account for acc in roster):
                print(
                    f"WARNING: account {account!r} from .env is not in the DLL roster "
                    "shown above; orders may target the wrong account.",
                    file=sys.stderr,
                )

            # 1. Query initial position
            try:
                pos = client.get_position(ticker, exchange=exchange, account=account)
                print(f"Initial custody position for {ticker}: {pos.quantity} shares @ {pos.average_price:.2f}")
            except Exception as exc:
                print(f"Could not query initial custody position: {exc}")

            # 2. Submit test limit buy order (far below market price for safe testing).
            #    The routing password set on the client is used automatically.
            print(f"Submitting test limit buy order for {ticker}...")
            order_id = client.send_buy_order(
                ticker,
                exchange=exchange,
                account=account,
                price=1.0,  # Safe test price far below market
                quantity=100,  # 1 standard lot of PETR4 shares on B3
            )
            # This is the LOCAL order ID for this session (not the permanent
            # Profit order ID); watch [TM] lines for the acceptance chain.
            print(f"Order submitted. Local order ID: {order_id}")

            # 3. Cancel test order
            print(f"Cancelling order #{order_id}...")
            client.cancel_order(account, order_id)
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
