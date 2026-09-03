"""File-based sink for CSV and Parquet output.

CSV is implemented with the stdlib ``csv`` module (no extra dependencies).
Parquet requires the optional ``parquet`` extra (``duckdb``) and is written
columnar + compressed, which is well suited for large tick datasets.

Both formats write two files under ``output_dir``: ``trades.*`` and
``daily_candles.*``. Re-runs append to CSV; Parquet writes one file per
flush batch (timestamped) because Parquet is not append-friendly.
"""

from __future__ import annotations

import csv
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

from profitdll_wrapper.ingest._base import BufferedSink
from profitdll_wrapper.ingest.schema import (
    DAILY_CANDLE_COLUMNS,
    TRADE_COLUMNS,
    candle_column_names,
    trade_column_names,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_TRADES_CSV = "trades.csv"
_CANDLES_CSV = "daily_candles.csv"
# Maps the schema's SQLite affinity (column tuple slot 2) to DuckDB types.
_DUCKDB_TYPES: Final[dict[str, str]] = {
    "TEXT": "VARCHAR",
    "INTEGER": "BIGINT",
    "REAL": "DOUBLE",
}


class CsvSink(BufferedSink):
    """Persists trades and daily candles to CSV or Parquet files.

    Args:
        output_dir: Directory where output files are written (created if missing).
        format: ``"csv"`` (stdlib) or ``"parquet"`` (requires the ``parquet`` extra).
        batch_size: Buffer size before an automatic flush.
        assume_b3_local: See
            :class:`~profitdll_wrapper.ingest._base.BufferedSink`.
    """

    def __init__(
        self,
        output_dir: Path | str,
        *,
        format: str = "csv",
        batch_size: int = 500,
        assume_b3_local: bool = False,
    ) -> None:
        super().__init__(batch_size=batch_size, assume_b3_local=assume_b3_local)
        self._format = format.strip().lower()
        if self._format not in ("csv", "parquet"):
            msg = f"Unsupported file format {format!r}; expected 'csv' or 'parquet'."
            raise ValueError(msg)
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if self._format == "csv":
            self._ensure_csv_headers()

    # ------------------------------------------------------------------ #
    # CSV
    # ------------------------------------------------------------------ #
    def _ensure_csv_headers(self) -> None:
        trades_path = self._output_dir / _TRADES_CSV
        candles_path = self._output_dir / _CANDLES_CSV
        if not trades_path.exists() or trades_path.stat().st_size == 0:
            with trades_path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(trade_column_names())
        if not candles_path.exists() or candles_path.stat().st_size == 0:
            with candles_path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(candle_column_names())

    def _flush_trades(self, rows: Sequence[tuple[object, ...]]) -> None:
        if self._format == "csv":
            self._append_csv(self._output_dir / _TRADES_CSV, rows)
        else:
            self._append_parquet("trades", rows, TRADE_COLUMNS)

    def _flush_candles(self, rows: Sequence[tuple[object, ...]]) -> None:
        if self._format == "csv":
            self._append_csv(self._output_dir / _CANDLES_CSV, rows)
        else:
            self._append_parquet("daily_candles", rows, DAILY_CANDLE_COLUMNS)

    def _append_csv(self, path: Path, rows: Sequence[tuple[object, ...]]) -> None:
        with self._lock, path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

    # ------------------------------------------------------------------ #
    # Parquet
    # ------------------------------------------------------------------ #
    def _append_parquet(
        self,
        table: str,
        rows: Sequence[tuple[object, ...]],
        columns: Sequence[tuple[str, str, str]],
    ) -> None:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - extra not installed
            msg = "Parquet output requires the 'parquet' extra (duckdb). Install it: uv sync --extra parquet"
            raise ImportError(msg) from exc

        col_defs = ", ".join(f'"{c[0]}" {_DUCKDB_TYPES.get(c[1], "VARCHAR")}' for c in columns)
        col_sql = ", ".join(f'"{c[0]}"' for c in columns)
        placeholders = ", ".join(["?"] * len(columns))

        # Each flush becomes its own timestamped file; Parquet has no append.
        # The scratch database is in-memory: the only file touched is the target.
        ts = int(time.time() * 1000)
        path = self._output_dir / f"{table}_{ts}.parquet"
        # COPY does not support bound parameters in DuckDB; doubling single
        # quotes keeps a quote inside ``output_dir`` from breaking the literal.
        dest = path.as_posix().replace("'", "''")
        with self._lock:
            con = duckdb.connect()
            try:
                con.execute(f"CREATE TABLE data ({col_defs})")
                con.executemany(
                    # identifiers come from the static schema; values are bound
                    f"INSERT INTO data ({col_sql}) VALUES ({placeholders})",  # nosec B608
                    list(rows),
                )
                con.execute(f"COPY data TO '{dest}' (FORMAT PARQUET)")
            finally:
                con.close()

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    @property
    def format(self) -> str:
        return self._format


__all__ = ["CsvSink"]
