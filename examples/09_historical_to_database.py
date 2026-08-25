"""Historical Trades to Database (SQLite sink) example.

Demonstrates the programmatic ingestion API: requesting tick-by-tick
historical trades (`get_history_trades`) and persisting them to a SQLite
database via the `profitdll_wrapper.ingest` subpackage.

This is the same use case the `profitdll-ingest` CLI covers, but shown as
embedded code so you can customize the sink (CSV, Parquet, PostgreSQL), the
tickers, and the run lifecycle.

Execution:
    uv run python examples/09_historical_to_database.py

Environment overrides:
    HIST_TICKER     default PETR4
    HIST_EXCHANGE   default B
    HIST_DB         default ./data/example_history.db
    CI_TIMEOUT      optional seconds before auto-stop (CI / smoke runs)
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import ProfitClient
from profitdll_wrapper.ingest import create_sink, ingest_history

setup_dll_path()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("history_to_database")


def main() -> int:
    key, user, password, _ = load_credentials()
    if not (key and user and password):
        logger.error(
            "Missing credentials. Set ACTIVATION_KEY, USER, and PASSWORD in .env"
        )
        return 2

    ticker = os.environ.get("HIST_TICKER", "PETR4")
    exchange = os.environ.get("HIST_EXCHANGE", "B")
    db_path = Path(os.environ.get("HIST_DB", "./data/example_history.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Define historical interval (last 3 days).
    now = datetime.now()
    start_date = (now - timedelta(days=3)).strftime("%d/%m/%Y 09:00:00")
    end_date = now.strftime("%d/%m/%Y %H:%M:%S")

    sink = create_sink("sqlite", db_url=str(db_path), batch_size=200)
    logger.info("SQLite sink ready at %s", db_path)

    try:
        client = ProfitClient(
            activation_key=key,
            user=user,
            password=password,
            mode="market_data",
            auto_resubscribe=True,
        )
        with client:
            logger.info("Connected! Requesting trade history for %s...", ticker)

            # Optional CI auto-stop so the example terminates on its own.
            if os.environ.get("CI_TIMEOUT"):
                run_time = float(os.environ["CI_TIMEOUT"])
                threading.Timer(run_time, client.stop).start()

            stats = ingest_history(
                client=client,
                sink=sink,
                tickers=[(ticker, exchange)],
                start_date=start_date,
                end_date=end_date,
                data_types=["trades"],
                inactivity_timeout=float(os.environ.get("INACTIVITY_TIMEOUT", "15")),
                max_timeout=float(os.environ.get("MAX_TIMEOUT", "300")),
            )
    except Exception as exc:
        logger.error("Ingestion failed: %s", exc)
        return 1
    finally:
        sink.close()

    print("\n=== Ingestion Summary ===")
    print(f"Ticker:     {ticker} ({exchange})")
    print(f"Interval:   {start_date}  ->  {end_date}")
    print(f"Elapsed:    {stats.elapsed_seconds:.2f}s")
    print(f"Trades:     {stats.trades_written}")
    print(f"Database:   {db_path.resolve()}")

    # Show how to read the data back.
    if db_path.exists():
        print("\n--- Sample rows (most recent 5 trades) ---")
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                'SELECT ticker, trade_number, price, quantity, timestamp FROM "trades" '
                'ORDER BY timestamp DESC LIMIT 5'
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            print(f"  {row[0]} #{row[1]}  price={row[2]:.2f}  qty={row[3]}  @ {row[4]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
