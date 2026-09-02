"""Tick-by-Tick Historical Trades Download & Corporate Actions Stream example.

Demonstrates:
  1. Streaming tick-by-tick historical trades (`get_history_trades`) delivered via `Event.HISTORICAL_TRADE`;
  2. Subscribing to real-time corporate action notifications (dividends, splits, adjustments) via `subscribe_adjust_history` delivered via `Event.ADJUST_HISTORY`;
  3. Handling invalid ticker notifications via `Event.INVALID_TICKER`.

Execution:
    uv run python examples/08_corporate_actions_and_history.py
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import (
    AdjustHistory,
    Event,
    InvalidTickerEvent,
    ProfitClient,
    Trade,
)

setup_dll_path()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("history_and_adjusts")


def main() -> int:
    key, user, password, _, _ = load_credentials()
    if not (key and user and password):
        logger.error("Missing credentials. Please set PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, and PROFITDLL_PASSWORD in .env")
        return 2

    ticker = os.environ.get("HIST_TICKER", "PETR4")
    exchange = os.environ.get("HIST_EXCHANGE", "B")

    # Define historical interval (last 3 days)
    now = datetime.now()
    start_date = (now - timedelta(days=3)).strftime("%d/%m/%Y 09:00:00")
    end_date = now.strftime("%d/%m/%Y %H:%M:%S")

    logger.info("Initializing ProfitClient in 'market_data' mode...")
    try:
        with ProfitClient(
            activation_key=key,
            user=user,
            password=password,
            mode="market_data",
            auto_resubscribe=True,
        ) as client:
            logger.info("Connected!")

            # 1. Register historical trade and corporate action handlers
            @client.on(Event.HISTORICAL_TRADE)
            def on_historical_trade(trade: Trade) -> None:
                logger.info(
                    "HISTORICAL TRADE: %s | Time: %s | Price: %.2f | Qty: %d | Vol: %.2f",
                    trade.asset.ticker, trade.timestamp, trade.price, trade.quantity, trade.volume
                )

            @client.on(Event.ADJUST_HISTORY)
            def on_adjust_history(adjust: AdjustHistory) -> None:
                logger.info(
                    "CORPORATE ACTION / ADJUSTMENT [%s]: Type=%s | Value=%.4f | Date=%s | Affects Price=%s",
                    adjust.asset.ticker, adjust.adjust_type, adjust.value, adjust.adjust_date, adjust.affect_price
                )

            @client.on(Event.INVALID_TICKER)
            def on_invalid_ticker(evt: InvalidTickerEvent) -> None:
                logger.warning("INVALID TICKER ALERT: %s on exchange %s", evt.asset.ticker, evt.asset.exchange)

            # 2. Request tick-by-tick trade history
            logger.info("Requesting historical trade ticks for %s (%s to %s)...", ticker, start_date, end_date)
            try:
                client.get_history_trades(ticker, start_date=start_date, end_date=end_date, exchange=exchange)
            except Exception as exc:
                logger.warning("Could not request trade history: %s", exc)

            # 3. Subscribe to corporate action notifications
            logger.info("Subscribing to corporate actions and adjustments for %s...", ticker)
            try:
                client.subscribe_adjust_history(ticker, exchange=exchange)
            except Exception as exc:
                logger.warning("Could not subscribe to corporate actions: %s", exc)

            print("\n=== Collecting Historical Trades & Corporate Actions ===")
            print("Press Ctrl+C to exit.\n")

            if os.environ.get("CI_TIMEOUT"):
                run_time = float(os.environ["CI_TIMEOUT"])
                logger.info("Running for %.1f seconds (CI_TIMEOUT)...", run_time)
                timer = threading.Timer(run_time, client.stop)
                timer.start()
                try:
                    client.run()
                finally:
                    timer.cancel()
            else:
                client.run()

    except KeyboardInterrupt:
        logger.info("Manual shutdown.")
    except Exception as exc:
        logger.error("Error querying history/adjustments: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
