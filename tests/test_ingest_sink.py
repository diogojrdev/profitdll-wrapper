"""Unit tests for SQLite and CSV historical data sinks."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from profitdll_wrapper._types.messages import DailyCandle
from profitdll_wrapper._types.models import AssetId, Trade
from profitdll_wrapper.ingest.csv_sink import CsvSink
from profitdll_wrapper.ingest.schema import candle_column_names, trade_column_names
from profitdll_wrapper.ingest.sink import DataSink, create_sink
from profitdll_wrapper.ingest.sqlite_sink import SqliteSink


def make_trade(ticker: str = "VALE3", exchange: str = "B", trade_number: int = 1) -> Trade:
    return Trade(
        asset=AssetId(ticker=ticker, exchange=exchange),
        trade_number=trade_number,
        price=62.50,
        quantity=500,
        volume=31250.0,
        buy_agent=101,
        sell_agent=202,
        trade_type=1,
        timestamp=datetime(2026, 8, 1, 10, 0, 0),
        is_edit=False,
    )


def make_candle(
    ticker: str = "VALE3", exchange: str = "B", date: str = "01/08/2026 18:00:00.000"
) -> DailyCandle:
    return DailyCandle(
        asset=AssetId(ticker=ticker, exchange=exchange),
        date=date,
        open=60.0,
        high=63.0,
        low=59.5,
        close=62.5,
        volume=1_200_000.0,
        adjustment=0.0,
        max_limit=70.0,
        min_limit=55.0,
        volume_buyer=600_000.0,
        volume_seller=600_000.0,
        quantity=20_000,
        trades=1_500,
        open_interest=8_000,
        quantity_buyer=10_000,
        quantity_seller=10_000,
        trades_buyer=750,
        trades_seller=750,
    )


# --------------------------------------------------------------------------- #
# SQLite sink
# --------------------------------------------------------------------------- #
def test_sqlite_sink_creates_tables(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    sink = SqliteSink(db_url=str(db), batch_size=10)
    sink.close()

    conn = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()

    assert "trades" in tables
    assert "daily_candles" in tables


def test_sqlite_sink_writes_and_upserts_trades(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    sink = SqliteSink(db_url=str(db), batch_size=2)
    sink.write_trade(make_trade(trade_number=1))
    sink.write_trade(make_trade(trade_number=2))
    sink.close()

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            'SELECT ticker, trade_number, price FROM "trades" ORDER BY trade_number'
        ).fetchall()
    finally:
        conn.close()

    assert rows == [("VALE3", 1, 62.5), ("VALE3", 2, 62.5)]


def test_sqlite_sink_upsert_is_idempotent(tmp_path: Path) -> None:
    """Re-running the same extraction must not duplicate rows."""
    db = tmp_path / "test.db"

    sink1 = SqliteSink(db_url=str(db), batch_size=1)
    sink1.write_trade(make_trade(trade_number=1))
    sink1.close()

    sink2 = SqliteSink(db_url=str(db), batch_size=1)
    # Same primary key, different price (correction).
    sink2.write_trade(make_trade(trade_number=1))
    sink2.close()

    conn = sqlite3.connect(db)
    try:
        count = conn.execute('SELECT COUNT(*) FROM "trades"').fetchone()[0]
    finally:
        conn.close()

    assert count == 1


def test_sqlite_sink_writes_candles(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    sink = SqliteSink(db_url=str(db), batch_size=1)
    sink.write_candle(make_candle())
    sink.close()

    conn = sqlite3.connect(db)
    try:
        row = conn.execute('SELECT ticker, close FROM "daily_candles"').fetchone()
    finally:
        conn.close()

    assert row == ("VALE3", 62.5)


# --------------------------------------------------------------------------- #
# CSV sink
# --------------------------------------------------------------------------- #
def test_csv_sink_writes_header_and_rows(tmp_path: Path) -> None:
    sink = CsvSink(output_dir=tmp_path, format="csv", batch_size=1)
    sink.write_trade(make_trade())
    sink.close()

    trades_file = tmp_path / "trades.csv"
    assert trades_file.exists()
    with trades_file.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        first_data_row = next(reader)

    assert header == trade_column_names()
    assert first_data_row[0] == "VALE3"  # ticker
    assert first_data_row[2] == "1"  # trade_number


def test_csv_sink_appends_across_writes(tmp_path: Path) -> None:
    sink = CsvSink(output_dir=tmp_path, format="csv", batch_size=1)
    sink.write_trade(make_trade(trade_number=1))
    sink.write_trade(make_trade(trade_number=2))
    sink.close()

    with (tmp_path / "trades.csv").open(encoding="utf-8") as f:
        data_rows = list(csv.reader(f))[1:]  # skip header

    assert len(data_rows) == 2


def test_csv_sink_candles_header(tmp_path: Path) -> None:
    sink = CsvSink(output_dir=tmp_path, format="csv", batch_size=1)
    sink.write_candle(make_candle())
    sink.close()

    with (tmp_path / "daily_candles.csv").open(encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header == candle_column_names()


# --------------------------------------------------------------------------- #
# Parquet sink (requires the optional 'parquet' extra / duckdb)
# --------------------------------------------------------------------------- #
def _read_parquet_rows(path: Path) -> list[tuple[object, ...]]:
    duckdb = pytest.importorskip("duckdb")
    dest = path.as_posix().replace("'", "''")
    con = duckdb.connect()
    try:
        return [tuple(row) for row in con.execute(f"SELECT * FROM '{dest}'").fetchall()]
    finally:
        con.close()


def test_parquet_sink_writes_trades(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    sink = CsvSink(output_dir=tmp_path, format="parquet", batch_size=2)
    sink.write_trade(make_trade(trade_number=1))
    sink.write_trade(make_trade(trade_number=2))
    sink.close()

    files = sorted(tmp_path.glob("trades_*.parquet"))
    assert len(files) == 1
    rows = _read_parquet_rows(files[0])
    assert [(r[0], r[2], r[3]) for r in rows] == [("VALE3", 1, 62.5), ("VALE3", 2, 62.5)]


def test_parquet_sink_writes_candles(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    sink = CsvSink(output_dir=tmp_path, format="parquet", batch_size=1)
    sink.write_candle(make_candle())
    sink.close()

    files = sorted(tmp_path.glob("daily_candles_*.parquet"))
    assert len(files) == 1
    rows = _read_parquet_rows(files[0])
    assert rows[0][0] == "VALE3"
    assert rows[0][3] == 60.0  # open


def test_parquet_sink_survives_quote_in_output_dir(tmp_path: Path) -> None:
    """A single quote in output_dir must not break out of the COPY literal."""
    pytest.importorskip("duckdb")
    quoted_dir = tmp_path / "qu'ote"
    sink = CsvSink(output_dir=quoted_dir, format="parquet", batch_size=1)
    sink.write_trade(make_trade())
    sink.close()

    files = sorted(quoted_dir.glob("trades_*.parquet"))
    assert len(files) == 1
    assert _read_parquet_rows(files[0])[0][0] == "VALE3"


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def test_create_sink_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unknown sink backend"):
        create_sink("redis")


def test_create_sink_returns_sqlite(tmp_path: Path) -> None:
    sink = create_sink("sqlite", db_url=str(tmp_path / "f.db"))
    try:
        assert isinstance(sink, SqliteSink)
    finally:
        sink.close()


def test_sqlite_sink_satisfies_protocol(tmp_path: Path) -> None:
    sink = SqliteSink(db_url=str(tmp_path / "p.db"), batch_size=1)
    try:
        assert isinstance(sink, DataSink)
    finally:
        sink.close()


def test_closed_sink_rejects_writes(tmp_path: Path) -> None:
    sink = SqliteSink(db_url=str(tmp_path / "c.db"), batch_size=1)
    sink.close()
    with pytest.raises(RuntimeError, match="closed"):
        sink.write_trade(make_trade())
