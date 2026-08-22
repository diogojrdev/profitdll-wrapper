"""Pluggable :class:`DataSink` protocol and factory.

A sink consumes historical ``Trade`` ticks and ``DailyCandle`` summaries
emitted by the ProfitDLL callbacks and persists them to a backend. The
factory dispatches by backend name and lazy-imports optional backends so
the library core stays dependency-free.

Supported backends (``backend`` argument):

* ``"sqlite"``   — stdlib ``sqlite3``, default (no extra dependencies).
* ``"csv"``      — stdlib ``csv``.
* ``"parquet"``  — requires extra ``parquet`` (``duckdb``).
* ``"postgres"`` — requires extra ``postgres`` (``psycopg``); TimescaleDB-aware.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from profitdll_wrapper._types.messages import DailyCandle
    from profitdll_wrapper._types.models import Trade

_SUPPORTED = ("sqlite", "csv", "parquet", "postgres")


@runtime_checkable
class DataSink(Protocol):
    """Consumes historical market data records and persists them.

    Implementations must be safe to call from the dispatcher thread that
    delivers events. ``flush``/``close`` are called from the ingest runner
    once the stream ends.
    """

    def write_trade(self, trade: Trade) -> None:
        """Persists a single historical trade tick (idempotent UPSERT)."""
        ...

    def write_candle(self, candle: DailyCandle) -> None:
        """Persists a single daily candle (idempotent UPSERT)."""
        ...

    def flush(self) -> None:
        """Writes any buffered records to the underlying store."""
        ...

    def close(self) -> None:
        """Releases all resources held by the sink (idempotent)."""
        ...


def create_sink(
    backend: str,
    *,
    db_url: str | None = None,
    output_dir: Path | str | None = None,
    batch_size: int = 500,
) -> DataSink:
    """Builds a sink for the requested backend.

    Args:
        backend: One of ``sqlite``, ``csv``, ``parquet``, ``postgres``.
        db_url: Connection string for ``sqlite``/``postgres``. For SQLite use a
            filesystem path or ``sqlite:///path``; the default is
            ``./profit_data.db``. For PostgreSQL use a libpq URL.
        output_dir: Directory for ``csv``/``parquet`` output (created if missing).
        batch_size: Number of records buffered before an automatic flush.

    Raises:
        ValueError: If ``backend`` is not recognized.
        ImportError: If an optional backend is requested but its extra is not
            installed.
    """
    name = backend.strip().lower()
    if name not in _SUPPORTED:
        msg = f"Unknown sink backend {backend!r}. Expected one of: {_SUPPORTED}"
        raise ValueError(msg)

    if name == "sqlite":
        from profitdll_wrapper.ingest.sqlite_sink import SqliteSink

        return SqliteSink(db_url=db_url or "sqlite:///./profit_data.db", batch_size=batch_size)

    if name == "csv":
        from profitdll_wrapper.ingest.csv_sink import CsvSink

        out = Path(output_dir) if output_dir is not None else Path("./data")
        return CsvSink(output_dir=out, format="csv", batch_size=batch_size)

    if name == "parquet":
        from profitdll_wrapper.ingest.csv_sink import CsvSink

        out = Path(output_dir) if output_dir is not None else Path("./data")
        return CsvSink(output_dir=out, format="parquet", batch_size=batch_size)

    # name == "postgres"
    from profitdll_wrapper.ingest.postgres_sink import PostgresSink

    if not db_url:
        msg = "PostgreSQL sink requires db_url (e.g. postgresql://user:pass@host/db)"
        raise ValueError(msg)
    return PostgresSink(db_url=db_url, batch_size=batch_size)


__all__ = ["DataSink", "create_sink"]
