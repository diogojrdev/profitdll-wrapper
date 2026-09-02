"""Market Data Streamer & CSV / pandas DataFrame Exporter example.

Demonstrates:
  1. Connecting in market_data mode (`ProfitClient`);
  2. Querying session close (`get_last_daily_close`) and asset specification (`request_ticker_info`);
  3. Real-time subscriptions for Trades (`subscribe`), V2 Offer Book (`subscribe_offer_book`), and Price Depth (`subscribe_price_depth`);
  4. Real-time CSV logging and pandas DataFrame export;
  5. Safe execution even outside active market session hours.

Execution:
    uv run python examples/05_market_data_streamer.py
"""

from __future__ import annotations

import csv
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import (
    AssetInfo,
    Event,
    PriceBookSnapshot,
    ProfitClient,
    Trade,
)

setup_dll_path()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("market_data_streamer")


class MarketDataCollector:
    """Collects real-time market data ticks and appends them to CSV files and DataFrames."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.trades_csv_path = self.output_dir / "trades_stream.csv"
        self.trades_list: list[dict[str, Any]] = []

        if not self.trades_csv_path.exists():
            with open(self.trades_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "ticker", "price", "quantity", "volume", "aggressor", "is_edit"])

    def record_trade(self, trade: Trade) -> None:
        row = {
            "timestamp": str(trade.timestamp),
            "ticker": trade.asset.ticker,
            "price": trade.price,
            "quantity": trade.quantity,
            "volume": trade.volume,
            "aggressor": trade.trade_type.name if hasattr(trade.trade_type, "name") else str(trade.trade_type),
            "is_edit": trade.is_edit,
        }
        self.trades_list.append(row)

        with open(self.trades_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                row["timestamp"], row["ticker"], row["price"], row["quantity"],
                row["volume"], row["aggressor"], row["is_edit"]
            ])

        logger.info(
            "TRADE: %s | Price: %.2f | Qty: %d | Aggressor: %s",
            trade.asset.ticker, trade.price, trade.quantity, row["aggressor"]
        )

    def to_dataframe(self) -> Any:
        """Converts collected trades list to pandas DataFrame if pandas is installed."""
        try:
            import pandas as pd  # type: ignore[import-not-found]
            return pd.DataFrame(self.trades_list)
        except ImportError:
            logger.warning("pandas is not installed in current environment. Returning raw dict list.")
            return self.trades_list


def main() -> int:
    key, user, password, _, _ = load_credentials()
    if not (key and user and password):
        logger.error("Missing credentials. Please set PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, and PROFITDLL_PASSWORD in .env")
        return 2

    ticker = os.environ.get("STREAM_TICKER", "PETR4")
    exchange = os.environ.get("STREAM_EXCHANGE", "B")

    collector = MarketDataCollector(output_dir=Path("./market_data_output"))

    logger.info("Initializing ProfitClient in 'market_data' mode...")
    try:
        with ProfitClient(
            activation_key=key,
            user=user,
            password=password,
            mode="market_data",
            auto_resubscribe=True,
        ) as client:
            logger.info("Connected successfully! Auto-resubscribe enabled.")

            # 1. Query previous closing price and asset specification info
            try:
                close_price = client.get_last_daily_close(ticker, exchange=exchange, adjusted=True)
                logger.info("Previous Daily Close for %s: $ %.2f", ticker, close_price)
            except Exception as e:
                logger.warning("Could not retrieve previous session daily close: %s", e)

            try:
                client.request_ticker_info(ticker, exchange=exchange)
            except Exception as e:
                logger.warning("Could not request asset info: %s", e)

            # 2. Register event handlers
            @client.on(Event.ASSET_INFO)
            def on_asset_info(info: AssetInfo) -> None:
                logger.info(
                    "ASSET SPECIFICATION: %s (%s) | Lot Size: %d | Min Tick: %.4f | ISIN: %s",
                    info.asset.ticker, info.name, info.lot_size,
                    info.min_price_increment, info.isin
                )

            @client.on(Event.TRADE)
            def on_trade(trade: Trade) -> None:
                collector.record_trade(trade)

            @client.on(Event.PRICE_SNAPSHOT)
            def on_book_snapshot(snapshot: PriceBookSnapshot) -> None:
                buy_top = snapshot.buy_levels[0].price if snapshot.buy_levels else 0.0
                sell_top = snapshot.sell_levels[0].price if snapshot.sell_levels else 0.0
                logger.info(
                    "BOOK SNAPSHOT [%s]: Top Bid=%.2f | Top Ask=%.2f",
                    snapshot.asset.ticker, buy_top, sell_top
                )

            # 3. Subscribe to market data feeds
            logger.info("Subscribing to trade ticks and offer books for %s...", ticker)
            client.subscribe(ticker, exchange=exchange)
            client.subscribe_offer_book(ticker, exchange=exchange)
            client.subscribe_price_depth(ticker, exchange=exchange)

            print("\n=== Market Data Collector Active ===")
            print(f"Real-time CSV logging output: {collector.trades_csv_path.resolve()}")
            print("Press Ctrl+C to stop streaming.\n")

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
        logger.info("Shutdown requested by user.")
    except Exception as exc:
        logger.error("Error in market data streamer: %s", exc)
        return 1

    df_summary = collector.to_dataframe()
    logger.info("Total trade ticks collected during session: %d", len(collector.trades_list))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
