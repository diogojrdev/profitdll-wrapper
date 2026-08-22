"""Schema definitions for historical data sinks.

Column lists and DDL are derived in one place so SQLite, CSV and PostgreSQL
backends never drift apart. Row mappers convert the library's immutable
dataclasses into the flat tuples/dicts the sinks persist.
"""

from __future__ import annotations

from typing import Final

from profitdll_wrapper._types.messages import DailyCandle
from profitdll_wrapper._types.models import Trade

# --------------------------------------------------------------------------- #
# Trades
# --------------------------------------------------------------------------- #
# (column name, SQLite affinity, PostgreSQL type). PK columns are NOT NULL.
TRADE_COLUMNS: Final[list[tuple[str, str, str]]] = [
    ("ticker", "TEXT", "TEXT"),
    ("exchange", "TEXT", "TEXT"),
    ("trade_number", "INTEGER", "BIGINT"),
    ("price", "REAL", "DOUBLE PRECISION"),
    ("quantity", "INTEGER", "BIGINT"),
    ("volume", "REAL", "DOUBLE PRECISION"),
    ("buy_agent", "INTEGER", "INTEGER"),
    ("sell_agent", "INTEGER", "INTEGER"),
    ("trade_type", "INTEGER", "SMALLINT"),
    ("timestamp", "TEXT", "TIMESTAMPTZ"),
    ("is_edit", "INTEGER", "BOOLEAN"),
]
TRADE_PK: Final[list[str]] = ["ticker", "exchange", "trade_number"]
# PostgreSQL/TimescaleDB PK must include the time column to allow hypertable
# partitioning. The logical business key (TRADE_PK) is still enforced via a
# UNIQUE index for UPSERT idempotency.
TRADE_PK_POSTGRES: Final[list[str]] = ["ticker", "exchange", "trade_number", "timestamp"]
# Column used to partition / index time-series queries.
TRADE_TIME_COLUMN: Final[str] = "timestamp"

# --------------------------------------------------------------------------- #
# Daily candles
# --------------------------------------------------------------------------- #
DAILY_CANDLE_COLUMNS: Final[list[tuple[str, str, str]]] = [
    ("ticker", "TEXT", "TEXT"),
    ("exchange", "TEXT", "TEXT"),
    ("date", "TEXT", "TEXT"),
    ("open", "REAL", "DOUBLE PRECISION"),
    ("high", "REAL", "DOUBLE PRECISION"),
    ("low", "REAL", "DOUBLE PRECISION"),
    ("close", "REAL", "DOUBLE PRECISION"),
    ("volume", "REAL", "DOUBLE PRECISION"),
    ("adjustment", "REAL", "DOUBLE PRECISION"),
    ("max_limit", "REAL", "DOUBLE PRECISION"),
    ("min_limit", "REAL", "DOUBLE PRECISION"),
    ("volume_buyer", "REAL", "DOUBLE PRECISION"),
    ("volume_seller", "REAL", "DOUBLE PRECISION"),
    ("quantity", "INTEGER", "BIGINT"),
    ("trades", "INTEGER", "BIGINT"),
    ("open_interest", "INTEGER", "BIGINT"),
    ("quantity_buyer", "INTEGER", "BIGINT"),
    ("quantity_seller", "INTEGER", "BIGINT"),
    ("trades_buyer", "INTEGER", "BIGINT"),
    ("trades_seller", "INTEGER", "BIGINT"),
]
DAILY_CANDLE_PK: Final[list[str]] = ["ticker", "exchange", "date"]
DAILY_CANDLE_TIME_COLUMN: Final[str] = "date"


def trade_column_names(dialect: str = "sqlite") -> list[str]:
    """Returns ordered trade column names for the given dialect."""
    _ = dialect
    return [c[0] for c in TRADE_COLUMNS]


def candle_column_names(dialect: str = "sqlite") -> list[str]:
    """Returns ordered daily candle column names for the given dialect."""
    _ = dialect
    return [c[0] for c in DAILY_CANDLE_COLUMNS]


def trade_to_row(trade: Trade) -> tuple[object, ...]:
    """Maps a ``Trade`` dataclass to a flat tuple in column order."""
    return (
        trade.asset.ticker,
        trade.asset.exchange,
        trade.trade_number,
        trade.price,
        trade.quantity,
        trade.volume,
        trade.buy_agent,
        trade.sell_agent,
        trade.trade_type,
        trade.timestamp.isoformat(),
        bool(trade.is_edit),
    )


def candle_to_row(candle: DailyCandle) -> tuple[object, ...]:
    """Maps a ``DailyCandle`` dataclass to a flat tuple in column order."""
    return (
        candle.asset.ticker,
        candle.asset.exchange,
        candle.date,
        candle.open,
        candle.high,
        candle.low,
        candle.close,
        candle.volume,
        candle.adjustment,
        candle.max_limit,
        candle.min_limit,
        candle.volume_buyer,
        candle.volume_seller,
        candle.quantity,
        candle.trades,
        candle.open_interest,
        candle.quantity_buyer,
        candle.quantity_seller,
        candle.trades_buyer,
        candle.trades_seller,
    )


def _pg_type(col: tuple[str, str, str]) -> str:
    return col[2]


def sqlite_create_trades() -> str:
    """Returns the SQLite ``CREATE TABLE`` statement for the trades table."""
    cols = [f'"{c[0]}" {c[1]} NOT NULL' for c in TRADE_COLUMNS]
    pk = ", ".join(f'"{c}"' for c in TRADE_PK)
    return (
        'CREATE TABLE IF NOT EXISTS "trades" (\n  '
        + ",\n  ".join(cols)
        + f",\n  PRIMARY KEY ({pk})\n)"
    )


def sqlite_create_daily_candles() -> str:
    """Returns the SQLite ``CREATE TABLE`` statement for the daily_candles table."""
    cols = [f'"{c[0]}" {c[1]} NOT NULL' for c in DAILY_CANDLE_COLUMNS]
    pk = ", ".join(f'"{c}"' for c in DAILY_CANDLE_PK)
    return (
        'CREATE TABLE IF NOT EXISTS "daily_candles" (\n  '
        + ",\n  ".join(cols)
        + f",\n  PRIMARY KEY ({pk})\n)"
    )


def postgres_create_trades() -> str:
    """Returns the PostgreSQL ``CREATE TABLE`` statement for the trades table.

    Both the primary key and the unique business-key index include ``timestamp``
    because TimescaleDB requires the partitioning column in every unique index.
    UPSERT idempotency is preserved since a given ``trade_number`` always maps
    to the same timestamp on re-extraction.
    """
    cols = [f'"{c[0]}" {_pg_type(c)} NOT NULL' for c in TRADE_COLUMNS]
    pk = ", ".join(f'"{c}"' for c in TRADE_PK_POSTGRES)
    return (
        'CREATE TABLE IF NOT EXISTS "trades" (\n  '
        + ",\n  ".join(cols)
        + f",\n  PRIMARY KEY ({pk})\n)"
    )


def postgres_create_daily_candles() -> str:
    """Returns the PostgreSQL ``CREATE TABLE`` statement for the daily_candles table."""
    cols = [f'"{c[0]}" {_pg_type(c)} NOT NULL' for c in DAILY_CANDLE_COLUMNS]
    pk = ", ".join(f'"{c}"' for c in DAILY_CANDLE_PK)
    return (
        'CREATE TABLE IF NOT EXISTS "daily_candles" (\n  '
        + ",\n  ".join(cols)
        + f",\n  PRIMARY KEY ({pk})\n)"
    )


def sqlite_trades_index() -> str:
    """Returns the SQLite ``CREATE INDEX`` for time-range trade queries."""
    return 'CREATE INDEX IF NOT EXISTS "idx_trades_ts" ON "trades" ("ticker", "timestamp")'


def sqlite_daily_candles_index() -> str:
    """Returns the SQLite ``CREATE INDEX`` for daily candle date queries."""
    return (
        'CREATE INDEX IF NOT EXISTS "idx_daily_candles_date" ON "daily_candles" ("ticker", "date")'
    )


__all__ = [
    "DAILY_CANDLE_COLUMNS",
    "DAILY_CANDLE_PK",
    "DAILY_CANDLE_TIME_COLUMN",
    "TRADE_COLUMNS",
    "TRADE_PK",
    "TRADE_PK_POSTGRES",
    "TRADE_TIME_COLUMN",
    "candle_column_names",
    "candle_to_row",
    "postgres_create_daily_candles",
    "postgres_create_trades",
    "sqlite_create_daily_candles",
    "sqlite_create_trades",
    "sqlite_daily_candles_index",
    "sqlite_trades_index",
    "trade_column_names",
    "trade_to_row",
]
