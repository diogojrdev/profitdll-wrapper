"""Positional price book depth & price level streaming example.

Demonstrates price book depth monitoring (`subscribe_price_depth`). Level updates
arrive via `Event.PRICE_LEVEL` and full snapshots via `Event.PRICE_SNAPSHOT`.

Prerequisites:
  * Windows 64-bit OS with Python 64-bit;
  * ProfitDLL binary available (defined via PROFITDLL_PATH env var or inside `dll/`);
  * Credentials set in `.env` file or environment variables.

Execution:

    uv run python examples/02_price_depth.py
"""

from __future__ import annotations

import sys

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import (
    Event,
    PriceBookSnapshot,
    PriceLevel,
    ProfitClient,
)


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
            print(f"Connected successfully. Subscribing to price depth for {ticker}@{exchange}...")
            client.subscribe_price_depth(ticker, exchange=exchange)

            @client.on(Event.PRICE_LEVEL)
            def on_level(level: PriceLevel) -> None:
                kind = "theoretical" if level.is_theoretical else "real"
                print(
                    f"[{level.update_type.name:<10}] {level.side.name:4} | "
                    f"Pos: {level.position:<3} | Price: {level.price:>10.2f} | "
                    f"Qty: {level.quantity:<6} ({level.count} orders, {kind})"
                )

            @client.on(Event.PRICE_SNAPSHOT)
            def on_snapshot(snap: PriceBookSnapshot) -> None:
                print(f"--- Price Snapshot for {snap.asset.ticker} ---")
                for lvl in snap.sell_levels:
                    print(f"  SELL pos={lvl.position} {lvl.price:.2f} x{lvl.quantity}")
                for lvl in snap.buy_levels:
                    print(f"  BUY  pos={lvl.position} {lvl.price:.2f} x{lvl.quantity}")

            print("Listening for price book updates (Press Ctrl+C to exit)...")
            client.run()
    except KeyboardInterrupt:
        print("\nDisconnecting and exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
