"""Real-time trade tick streaming example (Market Data Mode).

Objective: Minimal functional example demonstrating how to connect, subscribe to an asset,
and print incoming trade ticks in real-time.

Prerequisites:
  * Windows 64-bit OS with Python 64-bit;
  * ProfitDLL binary available (defined via PROFITDLL_PATH env var or inside `dll/`);
  * Credentials set in `.env` file or environment variables.

Execution:

    uv run python examples/01_subscribe_ticker.py
"""

from __future__ import annotations

import sys

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import Event, ProfitClient, Trade


def main() -> int:
    setup_dll_path()
    activation_key, user, password, _, _ = load_credentials()

    if not (activation_key and user and password):
        print(
            "Missing credentials. Please define PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, "
            "and PROFITDLL_PASSWORD in your .env file or environment.",
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
            mode="market_data",
        ) as client:
            print(f"Connected successfully. Subscribing to {ticker}@{exchange}...")
            client.subscribe(ticker, exchange=exchange)

            @client.on(Event.TRADE)
            def on_trade(trade: Trade) -> None:
                print(
                    f"{trade.asset.ticker:<6} | Price: {trade.price:>10.2f} | "
                    f"Qty: {trade.quantity:<5} | Aggressor: {trade.trade_type:<4} | Edit: {trade.is_edit}"
                )

            print("Listening for incoming trade ticks (Press Ctrl+C to exit)...")
            client.run()
    except KeyboardInterrupt:
        print("\nDisconnecting and exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
