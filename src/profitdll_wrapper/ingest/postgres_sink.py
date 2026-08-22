"""PostgreSQL / TimescaleDB sink.

Requires the optional ``postgres`` extra (``psycopg``). Compatible with both
plain PostgreSQL and TimescaleDB: when the ``timescaledb`` extension is
available, the trades table is converted to a hypertable partitioned by
``timestamp`` for efficient time-series queries and compression.

Connection is established via a libpq URL, e.g.
``postgresql://profit:secret@localhost:5432/profit``.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import TYPE_CHECKING, Any

from profitdll_wrapper.ingest._base import BufferedSink
from profitdll_wrapper.ingest.schema import (
    DAILY_CANDLE_COLUMNS,
    TRADE_COLUMNS,
    TRADE_PK_POSTGRES,
    postgres_create_daily_candles,
    postgres_create_trades,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger("profitdll_wrapper.ingest.postgres")


def _require_psycopg() -> Any:
    """Imports psycopg3 lazily with an instructive error for the missing extra."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - extra not installed
        msg = (
            "PostgreSQL sink requires the 'postgres' extra (psycopg). "
            "Install it: uv sync --extra postgres"
        )
        raise ImportError(msg) from exc
    return psycopg


class PostgresSink(BufferedSink):
    """Persists trades and daily candles to a PostgreSQL / TimescaleDB database."""

    def __init__(self, db_url: str, batch_size: int = 500) -> None:
        super().__init__(batch_size=batch_size)
        psycopg = _require_psycopg()
        self._lock = threading.Lock()
        # autocommit=False so DDL + inserts share explicit transactions.
        self._conn = psycopg.connect(db_url)
        self._init_schema()

    def _init_schema(self) -> None:
        # Commit table DDL in its own transaction so a hypertable failure can
        # never roll the tables back out from under us.
        with self._lock, self._conn.cursor() as cur:
            cur.execute(postgres_create_trades())
            cur.execute(postgres_create_daily_candles())
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_trades_ts" ON "trades" ("ticker", "timestamp");'
            )
            self._conn.commit()
        # Hypertable conversion is best-effort: no-op on plain Postgres.
        self._maybe_create_hypertable()

    def _maybe_create_hypertable(self) -> None:
        try:
            with self._lock, self._conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
                cur.execute(
                    "SELECT create_hypertable('trades', 'timestamp', if_not_exists => TRUE);"
                )
                self._conn.commit()
        except Exception as exc:  # pragma: no cover - depends on server extensions
            # Plain Postgres (no TimescaleDB) or already a hypertable: keep the
            # plain table. Roll back only the failed hypertable statement.
            logger.debug("Hypertable conversion skipped: %s", exc)
            with contextlib.suppress(Exception):
                self._conn.rollback()

    def _build_upsert(self, table: str, columns: Sequence[tuple[str, str, str]]) -> str:
        col_names = [c[0] for c in columns]
        cols_sql = ", ".join(f'"{c}"' for c in col_names)
        placeholders = ", ".join(["%s"] * len(col_names))
        # Conflict target must match a real unique index. For trades this is the
        # full PK (includes timestamp, required by TimescaleDB hypertables).
        conflict_cols = TRADE_PK_POSTGRES if table == "trades" else ["ticker", "exchange", "date"]
        conflict_sql = ", ".join(f'"{c}"' for c in conflict_cols)
        non_conflict = [c for c in col_names if c not in conflict_cols]
        assignments = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in non_conflict)
        return (
            f'INSERT INTO "{table}" ({cols_sql}) VALUES ({placeholders}) '  # nosec B608
            f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {assignments}"
        )

    def _flush_trades(self, rows: Sequence[tuple[object, ...]]) -> None:
        sql = self._build_upsert("trades", TRADE_COLUMNS)
        self._exec_and_commit(sql, rows, "trades")

    def _flush_candles(self, rows: Sequence[tuple[object, ...]]) -> None:
        sql = self._build_upsert("daily_candles", DAILY_CANDLE_COLUMNS)
        self._exec_and_commit(sql, rows, "daily_candles")

    def _exec_and_commit(self, sql: str, rows: Sequence[tuple[object, ...]], table: str) -> None:
        # Roll back on failure so a single bad batch doesn't poison every
        # subsequent flush (Postgres keeps a transaction in "aborted" state
        # until ROLLBACK). Re-raise so the runner surfaces the real error.
        with self._lock, self._conn.cursor() as cur:
            try:
                cur.executemany(sql, rows)
                self._conn.commit()
            except Exception:
                with contextlib.suppress(Exception):
                    self._conn.rollback()
                logger.error("Failed to flush %d row(s) to %s", len(rows), table)
                raise

    def _on_close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["PostgresSink"]
