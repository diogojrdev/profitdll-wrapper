"""Historical data ingestion: pluggable sinks, runner, and CLI.

This subpackage consumes the asynchronous historical data stream produced by
ProfitDLL (``Event.HISTORICAL_TRADE`` / ``Event.DAILY``) and persists it to a
configurable backend. Backends with no third-party dependency (SQLite, CSV)
are always available; Parquet and PostgreSQL ship as optional extras.

Public surface:

* :class:`DataSink` — the sink protocol every backend implements.
* :func:`create_sink` — factory dispatching by backend name.
* :func:`ingest_history` — orchestrates a ProfitClient + sink ingestion run.
* :class:`IngestStats` — summary of a completed run.
"""

from __future__ import annotations

from profitdll_wrapper.ingest.runner import IngestStats, ingest_history
from profitdll_wrapper.ingest.sink import DataSink, create_sink

__all__ = ["DataSink", "IngestStats", "create_sink", "ingest_history"]
