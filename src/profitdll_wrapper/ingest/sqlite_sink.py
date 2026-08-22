"""SQLite sink backed by the stdlib ``sqlite3`` module.

Zero external dependencies. The default database is ``./profit_data.db``.
Both tables are created on demand with composite primary keys so re-running
an extraction is safe (rows are upserted).

Supports ``:memory:`` databases for testing.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import TYPE_CHECKING

from profitdll_wrapper.ingest._base import BufferedSink
from profitdll_wrapper.ingest.schema import (
    DAILY_CANDLE_COLUMNS,
    TRADE_COLUMNS,
    sqlite_create_daily_candles,
    sqlite_create_trades,
    sqlite_daily_candles_index,
    sqlite_trades_index,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def _normalize_db_url(db_url: str) -> str:
    """Accepts either a raw path or a ``sqlite:///path`` URL."""
    if db_url.startswith("sqlite:///"):
        return db_url[len("sqlite:///") :]
    if db_url.startswith("sqlite://"):
        return db_url[len("sqlite://") :]
    return db_url


def _placeholder_list(n: int) -> str:
    return ", ".join("?" * n)


class SqliteSink(BufferedSink):
    """Persists trades and daily candles to a SQLite database."""

    def __init__(self, db_url: str = "sqlite:///./profit_data.db", batch_size: int = 500) -> None:
        super().__init__(batch_size=batch_size)
        self._db_path = _normalize_db_url(db_url)
        # sqlite3 connections are not safe to share across threads; the ingest
        # runner calls write_* from the dispatcher thread, so guard with a lock.
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(sqlite_create_trades())
            cur.execute(sqlite_create_daily_candles())
            cur.execute(sqlite_trades_index())
            cur.execute(sqlite_daily_candles_index())
            self._conn.commit()

    def _flush_trades(self, rows: Sequence[tuple[object, ...]]) -> None:
        cols = ", ".join(f'"{c[0]}"' for c in TRADE_COLUMNS)
        # UPDATE columns are everything except the PK.
        non_pk = [c[0] for c in TRADE_COLUMNS if c[0] not in ("ticker", "exchange", "trade_number")]
        assignments = ", ".join(f'"{c}" = excluded."{c}"' for c in non_pk)
        placeholders = _placeholder_list(len(TRADE_COLUMNS))
        sql = (
            # nosec B608 - identifiers come from the static schema; values are bound
            f'INSERT INTO "trades" ({cols}) VALUES ({placeholders}) '  # nosec B608
            f'ON CONFLICT("ticker", "exchange", "trade_number") DO UPDATE SET {assignments}'
        )
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    def _flush_candles(self, rows: Sequence[tuple[object, ...]]) -> None:
        cols = ", ".join(f'"{c[0]}"' for c in DAILY_CANDLE_COLUMNS)
        non_pk = [c[0] for c in DAILY_CANDLE_COLUMNS if c[0] not in ("ticker", "exchange", "date")]
        assignments = ", ".join(f'"{c}" = excluded."{c}"' for c in non_pk)
        placeholders = _placeholder_list(len(DAILY_CANDLE_COLUMNS))
        sql = (
            f'INSERT INTO "daily_candles" ({cols}) VALUES ({placeholders}) '  # nosec B608
            f'ON CONFLICT("ticker", "exchange", "date") DO UPDATE SET {assignments}'
        )
        with self._lock:
            self._conn.executemany(sql, rows)
            self._conn.commit()

    def _on_close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def db_path(self) -> str:
        return self._db_path


__all__ = ["SqliteSink"]
