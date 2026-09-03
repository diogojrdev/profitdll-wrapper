"""Historical data ingestion: pluggable sinks, runner, and CLI.

This subpackage consumes the asynchronous historical data stream produced by
ProfitDLL (``Event.HISTORICAL_TRADE`` / ``Event.DAILY``) and persists it to a
configurable backend. Backends with no third-party dependency (SQLite, CSV)
are always available; Parquet and PostgreSQL ship as optional extras.

Public surface:

* :class:`DataSink` — the sink protocol every backend implements.
* :func:`create_sink` — factory dispatching by backend name.
* :func:`ingest_history` — one shared window for all tickers (legacy contract).
* :func:`ingest_windows` — serial multi-window runner (one request in flight,
  per-ticker windows, completion via the DLL progress callback).
* :class:`IngestStats` / :class:`TickerStats` — summary of a completed run.
"""

from __future__ import annotations

from profitdll_wrapper.ingest.runner import (
    IngestStats,
    TickerStats,
    ingest_history,
    ingest_windows,
)
from profitdll_wrapper.ingest.sink import DataSink, create_sink

__all__ = [
    "DataSink",
    "IngestStats",
    "TickerStats",
    "create_sink",
    "ingest_history",
    "ingest_windows",
]
