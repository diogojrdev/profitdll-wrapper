"""Live Smoke Test for profitdll-wrapper (Real Native DLL).

Unlike examples 01/02 (which block indefinitely in `client.run()` until Ctrl+C),
this script is self-terminating: connects, subscribes, collects real-time events for
a specified duration, shuts down, and outputs a validation report.

Validates in a single execution:
  * Package imports and initializations;
  * Native DLL loading (architecture, PROFITDLL_PATH resolution, calling convention);
  * Connection handshake (`connect()`);
  * Real trade events (non-null ticker, price, quantity) — P0;
  * With `--depth`: order book levels — P1.

Execution:

    uv run python examples/03_live_smoke.py
    uv run python examples/03_live_smoke.py --duration 30
    uv run python examples/03_live_smoke.py --depth
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import (
    Event,
    PriceBookSnapshot,
    PriceLevel,
    ProfitClient,
    Trade,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live smoke test for profitdll-wrapper against native DLL.")
    p.add_argument("--duration", type=float, default=20.0, help="Collection duration in seconds (default: 20.0).")
    p.add_argument("--depth", action="store_true", help="Validate P1 price book depth events as well.")
    p.add_argument("--ticker", default="PETR4", help="Asset ticker symbol (default: PETR4).")
    p.add_argument("--exchange", default="B", help="Exchange code (default: B for Bovespa).")
    p.add_argument("--connect-timeout", type=float, default=30.0, help="Connection wait timeout in seconds.")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    setup_dll_path()
    activation_key, user, password, _ = load_credentials()

    if not (activation_key and user and password):
        print(
            "Missing credentials. Please define PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, "
            "and PROFITDLL_PASSWORD in your .env file or environment.",
            file=sys.stderr,
        )
        return 2

    print(f"DLL Path   : {os.environ.get('PROFITDLL_PATH', '(default)')}")
    print(f"Target     : {args.ticker}@{args.exchange}")
    print(f"Duration   : {args.duration:.0f}s (depth={args.depth})")
    print("-" * 60)

    trades: list[Trade] = []
    levels: list[PriceLevel] = []
    snapshots: list[PriceBookSnapshot] = []
    errors: list[str] = []

    try:
        t0 = time.monotonic()
        with ProfitClient(
            activation_key=activation_key,
            user=user,
            password=password,
            mode="routing",
        ) as client:
            t_connect = time.monotonic() - t0
            print(f"CONNECT    : OK in {t_connect:.2f}s (LOGIN + MARKET_DATA + ROUTING).")

            client.subscribe(args.ticker, exchange=args.exchange)
            print(f"SUBSCRIBE  : {args.ticker}@{args.exchange} (trades) OK.")
            if args.depth:
                client.subscribe_price_depth(args.ticker, exchange=args.exchange)
                print(f"SUBSCRIBE  : {args.ticker}@{args.exchange} (depth) OK.")

            @client.on(Event.TRADE)
            def on_trade(trade: Trade) -> None:
                if len(trades) < 1000:
                    trades.append(trade)
                if len(trades) <= 20:
                    print(
                        f"TRADE      : {trade.asset.ticker:<6} | Price: {trade.price:>10.2f} | "
                        f"Qty: {trade.quantity:<5} | Aggressor: {trade.trade_type:<4} | Edit: {trade.is_edit}"
                    )

            if args.depth:

                @client.on(Event.PRICE_LEVEL)
                def on_level(level: PriceLevel) -> None:
                    if len(levels) < 1000:
                        levels.append(level)
                    if len(levels) <= 20:
                        kind = "theoretical" if level.is_theoretical else "real"
                        print(
                            f"LEVEL      : [{level.update_type.name:<10}] {level.side.name:4} | "
                            f"Pos: {level.position:<3} | Price: {level.price:>10.2f} | "
                            f"Qty: {level.quantity:<6} ({level.count} orders, {kind})"
                        )

                @client.on(Event.PRICE_SNAPSHOT)
                def on_snapshot(snap: PriceBookSnapshot) -> None:
                    snapshots.append(snap)
                    if len(snapshots) <= 5:
                        print(
                            f"SNAPSHOT   : {snap.asset.ticker} "
                            f"buy={len(snap.buy_levels)} sell={len(snap.sell_levels)}"
                        )

            @client.on(Event.ERROR)
            def on_error(ev: object) -> None:
                errors.append(repr(ev))
                print(f"ERROR      : {ev!r}", file=sys.stderr)

            timer = threading.Timer(args.duration, client.stop)
            timer.daemon = True
            timer.start()
            print(f"COLLECTING : {args.duration:.0f}s (Press Ctrl+C to cancel early)...")
            try:
                client.run()
            finally:
                timer.cancel()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as exc:
        print(f"FAILURE    : {type(exc).__name__}: {exc}", file=sys.stderr)
        name = type(exc).__name__
        if name in {"FileNotFoundError", "OSError"}:
            print(
                "Tip        : verify PROFITDLL_PATH / bitness (Python 64-bit vs DLL 64-bit).",
                file=sys.stderr,
            )
        return 1

    print("=" * 60)
    print("SMOKE TEST REPORT")
    print("=" * 60)
    print(f"Trades Received    : {len(trades)}")
    if trades:
        first = trades[0]
        non_null = bool(first.asset.ticker and first.price > 0 and first.quantity != 0)
        print(
            f"First Trade        : {first.asset.ticker} {first.price:.2f} x{first.quantity} "
            f"(valid fields: {non_null})"
        )
        print(f"  -> P0 (trades)   : {'PASSED' if non_null else 'FAILED (null fields)'}")
    else:
        print("  -> P0 (connection): PASSED (connected OK, 0 trades received - market may be closed)")
    if args.depth:
        print(f"Book Levels        : {len(levels)}")
        print(f"Book Snapshots     : {len(snapshots)}")
        if levels or snapshots:
            print("  -> P1 (depth)    : PASSED")
        else:
            print("  -> P1 (depth)    : NO EVENTS (market closed or depth inactive)")
    if errors:
        print(f"Handler Errors     : {len(errors)}")
        for e in errors[:5]:
            print(f"  - {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
