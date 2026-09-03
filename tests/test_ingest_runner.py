"""End-to-end tests for the ingestion runner using the fake backend.

These tests exercise the full pipeline: ProfitClient (market_data mode) +
FakeProfitBackend emitting historical trades -> ingest_history -> SQLite sink.
No native DLL is required.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from profitdll_wrapper import ProfitClient
from profitdll_wrapper._bindings.structures import TConnectorAssetIdentifier
from profitdll_wrapper.ingest import IngestStats, create_sink, ingest_history
from profitdll_wrapper.ingest.sqlite_sink import SqliteSink
from tests.fakes.backend import FakeProfitBackend

_FAKE_CREDS = dict(activation_key="fake_key", user="fake_user", password="fake_password")


def _asset_id(ticker: str, exchange: str) -> TConnectorAssetIdentifier:
    asset = TConnectorAssetIdentifier()
    asset.Version = 0
    asset.Ticker = ticker
    asset.Exchange = exchange
    return asset


def _make_backend() -> FakeProfitBackend:
    from profitdll_wrapper._bindings.enums import MARKET_DATA_STATES

    backend = FakeProfitBackend()
    backend.connect_states = MARKET_DATA_STATES
    return backend


def test_ingest_history_single_ticker(tmp_path: Path) -> None:
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    db = tmp_path / "ingest.db"
    sink = SqliteSink(db_url=str(db), batch_size=10)

    with client:
        # Schedule a few historical trades to be emitted shortly after the
        # request is issued. They arrive via the same callback path as the
        # real DLL (history_trade_callback -> dispatcher -> HISTORICAL_TRADE).
        def _emit_after_delay() -> None:
            time.sleep(0.3)
            asset = _asset_id("VALE3", "B")
            for i in range(5):
                backend.emit_history_trade(
                    asset, "2026-08-01 10:00:00", price=62.5, qty=100, trade_id=100 + i
                )

        import threading

        t = threading.Thread(target=_emit_after_delay, daemon=True)
        t.start()

        stats = ingest_history(
            client=client,
            sink=sink,
            tickers=[("VALE3", "B")],
            start_date="01/08/2026 09:00:00",
            end_date="04/08/2026 18:00:00",
            inactivity_timeout=1.0,
            max_timeout=10.0,
        )

    sink.close()

    assert isinstance(stats, IngestStats)
    assert len(stats.tickers) == 1
    # The fake emits trades async; the watchdog stops after the inactivity window.
    # We assert at least the request was issued and the run terminated cleanly.
    assert backend.history_trade_requests == [
        ("VALE3", "B", "01/08/2026 09:00:00", "04/08/2026 18:00:00")
    ]
    assert stats.elapsed_seconds < 10.0


def test_ingest_history_requires_tickers(tmp_path: Path) -> None:
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "x.db"), batch_size=1)
    with client:
        try:
            ingest_history(
                client=client,
                sink=sink,
                tickers=[],
                start_date="01/08/2026 09:00:00",
                end_date="02/08/2026 18:00:00",
            )
        except ValueError as exc:
            assert "at least one" in str(exc).lower()
        else:  # pragma: no cover - branch guard
            raise AssertionError("Expected ValueError for empty tickers list.")
    sink.close()


def test_ingest_history_rejects_unknown_data_type(tmp_path: Path) -> None:
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "y.db"), batch_size=1)
    with client:
        try:
            ingest_history(
                client=client,
                sink=sink,
                tickers=[("VALE3", "B")],
                start_date="01/08/2026 09:00:00",
                end_date="02/08/2026 18:00:00",
                data_types=["bogus"],
                inactivity_timeout=0.5,
                max_timeout=2.0,
            )
        except ValueError as exc:
            assert "unknown" in str(exc).lower() or "bogus" in str(exc)
        else:  # pragma: no cover - branch guard
            raise AssertionError("Expected ValueError for unknown data type.")
    sink.close()


def test_ingest_history_records_trades_in_db(tmp_path: Path) -> None:
    """Trades emitted by the fake backend must end up persisted in the sink."""
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    db = tmp_path / "trades_only.db"
    sink = SqliteSink(db_url=str(db), batch_size=2)

    import threading

    with client:

        def _emit() -> None:
            time.sleep(0.2)
            asset = _asset_id("PETR4", "B")
            # Emit more than batch_size (2) to exercise the auto-flush path.
            for i in range(3):
                backend.emit_history_trade(
                    asset, "2026-08-01 10:00:00", price=38.0, qty=200, trade_id=i + 1
                )

        emitter = threading.Thread(target=_emit, daemon=True)
        emitter.start()
        stats = ingest_history(
            client=client,
            sink=sink,
            tickers=[("PETR4", "B")],
            start_date="01/08/2026 09:00:00",
            end_date="04/08/2026 18:00:00",
            inactivity_timeout=0.8,
            max_timeout=8.0,
        )
    sink.close()

    conn = sqlite3.connect(db)
    try:
        count = conn.execute('SELECT COUNT(*) FROM "trades"').fetchone()[0]
    finally:
        conn.close()

    assert count == 3, f"Expected 3 trades in DB, got {count} (stats={stats})"


def test_create_sink_factory_in_module(tmp_path: Path) -> None:
    """The public factory should work via the package namespace."""
    sink = create_sink("sqlite", db_url=str(tmp_path / "factory.db"))
    sink.close()
    assert isinstance(sink, SqliteSink)


def test_ingest_history_first_event_timeout_marks_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A ticker the DLL never answers is flagged empty with a warning.

    Regression guard for the watchdog bug where a queued-but-unserved request
    was silently marked complete after ``inactivity_timeout`` without ever
    receiving a single event.
    """
    import logging

    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "empty.db"), batch_size=1)

    with client, caplog.at_level(logging.WARNING, logger="profitdll_wrapper.ingest"):
        stats = ingest_history(
            client=client,
            sink=sink,
            tickers=[("PETR4", "B")],
            start_date="01/08/2026 09:00:00",
            end_date="04/08/2026 18:00:00",
            inactivity_timeout=10.0,
            first_event_timeout=0.5,
            max_timeout=20.0,
        )
    sink.close()

    ts = stats.tickers[0]
    assert ts.empty is True
    assert ts.trades_written == 0
    assert ts.completed_by_progress is False
    assert any("no trades, candles or progress" in rec.message.lower() for rec in caplog.records)


def test_ingest_history_completes_by_progress(tmp_path: Path) -> None:
    """Progress reaching 100 completes the ticker (with a short drain)."""
    import threading

    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "progress.db"), batch_size=1)

    with client:

        def _emit() -> None:
            time.sleep(0.2)
            backend.emit_history_progress("PETR4", "B", 100)

        threading.Thread(target=_emit, daemon=True).start()
        stats = ingest_history(
            client=client,
            sink=sink,
            tickers=[("PETR4", "B")],
            start_date="01/08/2026 09:00:00",
            end_date="04/08/2026 18:00:00",
            inactivity_timeout=0.5,
            first_event_timeout=10.0,
            max_timeout=10.0,
        )
    sink.close()

    ts = stats.tickers[0]
    assert ts.completed_by_progress is True
    assert ts.empty is False


def test_ingest_history_twice_does_not_duplicate_writes(tmp_path: Path) -> None:
    """Handlers are removed at the end of each run (client.off)."""
    import threading

    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    db = tmp_path / "twice.db"
    sink = SqliteSink(db_url=str(db), batch_size=10)

    def _emit_later() -> None:
        time.sleep(0.2)
        asset = _asset_id("PETR4", "B")
        for i in range(3):
            backend.emit_history_trade(
                asset, "2026-08-01 10:00:00", price=38.0, qty=100, trade_id=i + 1
            )
        backend.emit_history_progress("PETR4", "B", 100)

    with client:
        emitter = threading.Thread(target=_emit_later, daemon=True)
        emitter.start()
        first = ingest_history(
            client=client,
            sink=sink,
            tickers=[("PETR4", "B")],
            start_date="01/08/2026 09:00:00",
            end_date="04/08/2026 18:00:00",
            inactivity_timeout=0.5,
            stop_client=False,
        )
        # Session must still be pumping after a non-stopping run.
        assert client._dispatcher._thread is not None
        assert client._dispatcher._thread.is_alive()

        emitter2 = threading.Thread(target=_emit_later, daemon=True)
        emitter2.start()
        second = ingest_history(
            client=client,
            sink=sink,
            tickers=[("PETR4", "B")],
            start_date="01/08/2026 09:00:00",
            end_date="04/08/2026 18:00:00",
            inactivity_timeout=0.5,
        )
    sink.close()

    assert first.trades_written == 3
    assert second.trades_written == 3

    conn = sqlite3.connect(db)
    try:
        count = conn.execute('SELECT COUNT(*) FROM "trades"').fetchone()[0]
    finally:
        conn.close()
    assert count == 3, f"expected 3 rows (no duplicate handlers), got {count}"
