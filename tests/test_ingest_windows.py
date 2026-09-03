"""Tests for the serial multi-window runner (ingest_windows).

Uses a scripted responder thread that watches the fake backend's request log
and answers each request in order — including DELAYED answers and stale
cross-window trades — reproducing, at unit level, the production incident
where one day's tape was recorded with another day's trades.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from profitdll_wrapper import ProfitClient
from profitdll_wrapper._bindings.structures import TConnectorAssetIdentifier
from profitdll_wrapper.ingest import ingest_windows
from profitdll_wrapper.ingest.sqlite_sink import SqliteSink
from tests.fakes.backend import FakeProfitBackend

_FAKE_CREDS = dict(activation_key="fake_key", user="fake_user", password="fake_password")

# Action types understood by the scripted responder.
# ("trade", ticker, when, trade_id)   -> emit a historical trade
# ("progress", ticker, progress)      -> emit progress for the asset
# ("invalid", ticker)                 -> emit an invalid-ticker notification
# ("sleep", seconds)                  -> delay before the next action
TradeAction = tuple[str, Any, Any, int]


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


def _dt(day: str, hhmmss: str = "10:00:00") -> datetime:
    return datetime.strptime(f"{day} {hhmmss}", "%d/%m/%Y %H:%M:%S")


class _ScriptedResponder:
    """Answers each issued request with a scripted list of DLL events."""

    def __init__(self, backend: FakeProfitBackend, script: list[list[tuple[Any, ...]]]) -> None:
        self._backend = backend
        self._script = script
        self._seen = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        deadline = time.monotonic() + 60.0
        while not self._stop.is_set() and self._seen < len(self._script):
            issued = len(self._backend.history_trade_requests)
            while self._seen < min(issued, len(self._script)):
                self._respond(self._seen)
                self._seen += 1
            if time.monotonic() > deadline:  # pragma: no cover - safety valve
                return
            time.sleep(0.01)

    def _respond(self, index: int) -> None:
        for action in self._script[index]:
            kind = action[0]
            if kind == "trade":
                _, ticker, when, trade_id = action
                self._backend.emit_history_trade(
                    _asset_id(ticker, "B"),
                    date="",
                    price=10.0,
                    qty=100,
                    trade_id=trade_id,
                    when=when,
                )
            elif kind == "progress":
                _, ticker, progress = action
                self._backend.emit_history_progress(ticker, "B", progress)
            elif kind == "invalid":
                _, ticker = action
                self._backend.emit_invalid_ticker(ticker, "B")
            elif kind == "sleep":
                time.sleep(action[1])
            else:  # pragma: no cover - script bug
                msg = f"Unknown action {kind!r}"
                raise AssertionError(msg)


def test_multi_window_purity_with_delayed_and_stale_responses(tmp_path: Path) -> None:
    """DoD 1 (unit repro): same tickers, two different windows, one session.

    Window A (27/08) requests are answered with a delay; window B (02/09)
    requests receive stale A-dated trades and trades of another ticker — all
    must be discarded, and each tape must only contain its own dates.
    """
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    db = tmp_path / "windows.db"
    sink = SqliteSink(db_url=str(db), batch_size=10)

    script = [
        # Request 1: PETR4 window A — delayed response, in-window trades.
        [
            ("sleep", 0.3),
            ("trade", "PETR4", _dt("27/08/2026", "10:01:00"), 1),
            ("trade", "PETR4", _dt("27/08/2026", "10:02:00"), 2),
            ("progress", "PETR4", 100),
        ],
        # Request 2: VALE3 window A.
        [
            ("sleep", 0.2),
            ("trade", "VALE3", _dt("27/08/2026", "10:05:00"), 3),
            ("progress", "VALE3", 100),
        ],
        # Request 3: PETR4 window B — stale A-dated trade (out of window),
        # stray trade of another ticker, then the real B trade.
        [
            ("trade", "PETR4", _dt("27/08/2026", "10:30:00"), 4),
            ("trade", "VALE3", _dt("02/09/2026", "10:30:00"), 5),
            ("trade", "PETR4", _dt("02/09/2026", "10:31:00"), 6),
            ("progress", "PETR4", 100),
        ],
        # Request 4: VALE3 window B.
        [("trade", "VALE3", _dt("02/09/2026", "11:00:00"), 7), ("progress", "VALE3", 100)],
    ]
    responder = _ScriptedResponder(backend, script)

    with client:
        responder.start()
        stats = ingest_windows(
            client=client,
            sink=sink,
            tickers=[
                ("PETR4", "B", "27/08/2026 10:00:00", "27/08/2026 16:55:00"),
                ("VALE3", "B", "27/08/2026 10:00:00", "27/08/2026 16:55:00"),
                ("PETR4", "B", "02/09/2026 10:00:00", "02/09/2026 16:55:00"),
                ("VALE3", "B", "02/09/2026 10:00:00", "02/09/2026 16:55:00"),
            ],
            inactivity_timeout=0.4,
            first_event_timeout=10.0,
            request_timeout=30.0,
        )
        responder.stop()
    sink.close()

    assert len(stats.tickers) == 4
    assert stats.trades_written == 5

    # Every request completed via the progress callback (the real signal).
    assert all(t.completed_by_progress for t in stats.tickers), stats.tickers
    assert not any(t.empty or t.timed_out or t.invalid for t in stats.tickers)

    # Window A tapes hold only A-dated trades; window B only B-dated.
    assert [(t.ticker, t.trades_written) for t in stats.tickers] == [
        ("PETR4", 2),
        ("VALE3", 1),
        ("PETR4", 1),
        ("VALE3", 1),
    ]

    # Contamination defenses: request 3 got one out-of-window + one stray.
    req3 = stats.tickers[2]
    assert req3.discarded_out_of_window == 1
    assert req3.discarded_stray == 1

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            'SELECT ticker, timestamp FROM "trades" ORDER BY trade_number'
        ).fetchall()
    finally:
        conn.close()
    dates = {(ticker, ts[:10]) for ticker, ts in rows}
    assert dates == {
        ("PETR4", "2026-08-27"),
        ("VALE3", "2026-08-27"),
        ("PETR4", "2026-09-02"),
        ("VALE3", "2026-09-02"),
    }, rows


def test_requests_are_strictly_serial(tmp_path: Path) -> None:
    """The next request is only issued after the current one completes."""
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "serial.db"), batch_size=10)

    # The responder only answers when it sees a request; if the runner fired
    # everything up front, both requests would exist before any response.
    order: list[tuple[str, str]] = []
    lock = threading.Lock()

    class _OrderedResponder(_ScriptedResponder):
        def _respond(self, index: int) -> None:
            with lock:
                order.append(("respond", backend.history_trade_requests[index][0]))
            super()._respond(index)

    script = [
        [("sleep", 0.2), ("progress", "PETR4", 100)],
        [("sleep", 0.2), ("progress", "VALE3", 100)],
    ]
    responder = _OrderedResponder(backend, script)

    with client:
        responder.start()
        stats = ingest_windows(
            client=client,
            sink=sink,
            tickers=[
                ("PETR4", "B", "01/09/2026 10:00:00", "01/09/2026 16:00:00"),
                ("VALE3", "B", "02/09/2026 10:00:00", "02/09/2026 16:00:00"),
            ],
            inactivity_timeout=0.3,
            first_event_timeout=10.0,
        )
        responder.stop()
    sink.close()

    # Request 2 was issued only after request 1 was answered and completed:
    # the responder answered in order and the run finished cleanly.
    assert [r[0] for r in backend.history_trade_requests] == ["PETR4", "VALE3"]
    assert order == [("respond", "PETR4"), ("respond", "VALE3")]
    assert len(stats.tickers) == 2
    assert stats.elapsed_seconds > 0


def test_first_event_timeout_marks_empty_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A request the DLL never answers ends as empty + warning, not silence."""
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "empty.db"), batch_size=10)

    import logging

    with client, caplog.at_level(logging.WARNING, logger="profitdll_wrapper.ingest"):
        stats = ingest_windows(
            client=client,
            sink=sink,
            tickers=[("WDOQ26", "B", "01/09/2026 10:00:00", "01/09/2026 16:00:00")],
            first_event_timeout=0.5,
            inactivity_timeout=5.0,
        )
    sink.close()

    assert len(stats.tickers) == 1
    ts = stats.tickers[0]
    assert ts.empty is True
    assert ts.trades_written == 0
    assert ts.completed_by_progress is False
    assert any("no trades or progress" in rec.message.lower() for rec in caplog.records)


def test_request_timeout_marks_timed_out(tmp_path: Path) -> None:
    """Progress trickling without reaching 100 ends at the per-request ceiling."""
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "timeout.db"), batch_size=10)

    script = [
        # Progress stalls at 40 and no further events arrive.
        [("sleep", 0.1), ("progress", "PETR4", 40)],
    ]
    responder = _ScriptedResponder(backend, script)

    with client:
        responder.start()
        stats = ingest_windows(
            client=client,
            sink=sink,
            tickers=[("PETR4", "B", "01/09/2026 10:00:00", "01/09/2026 16:00:00")],
            first_event_timeout=5.0,
            inactivity_timeout=5.0,
            request_timeout=1.0,
        )
        responder.stop()
    sink.close()

    ts = stats.tickers[0]
    assert ts.timed_out is True
    assert ts.completed_by_progress is False


def test_max_timeout_skips_remaining_requests(tmp_path: Path) -> None:
    """Once the run ceiling is hit, pending requests are skipped as timed out."""
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "ceiling.db"), batch_size=10)

    with client:
        stats = ingest_windows(
            client=client,
            sink=sink,
            tickers=[
                ("AAA3", "B", "01/09/2026 10:00:00", "01/09/2026 16:00:00"),
                ("BBB3", "B", "01/09/2026 10:00:00", "01/09/2026 16:00:00"),
            ],
            first_event_timeout=10.0,
            inactivity_timeout=10.0,
            request_timeout=10.0,
            max_timeout=1.0,
        )
    sink.close()

    assert [t.ticker for t in stats.tickers if t.timed_out] == ["AAA3", "BBB3"]
    assert backend.history_trade_requests == [
        ("AAA3", "B", "01/09/2026 10:00:00", "01/09/2026 16:00:00")
    ]


def test_invalid_ticker_completes_request(tmp_path: Path) -> None:
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "invalid.db"), batch_size=10)

    script = [[("sleep", 0.1), ("invalid", "ZZZZ9")]]
    responder = _ScriptedResponder(backend, script)

    with client:
        responder.start()
        stats = ingest_windows(
            client=client,
            sink=sink,
            tickers=[("ZZZZ9", "B", "01/09/2026 10:00:00", "01/09/2026 16:00:00")],
            first_event_timeout=10.0,
        )
        responder.stop()
    sink.close()

    assert stats.tickers[0].invalid is True
    assert stats.tickers[0].trades_written == 0


def test_stop_client_false_keeps_session_usable(tmp_path: Path) -> None:
    """Two ingest_windows runs on one client: no duplicate handlers, session alive."""
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "twice.db"), batch_size=10)

    script = [
        [
            ("sleep", 0.1),
            ("trade", "PETR4", _dt("01/09/2026", "10:01:00"), 1),
            ("progress", "PETR4", 100),
        ],
        [
            ("sleep", 0.1),
            ("trade", "PETR4", _dt("02/09/2026", "10:01:00"), 2),
            ("progress", "PETR4", 100),
        ],
    ]
    responder = _ScriptedResponder(backend, script)

    with client:
        responder.start()
        first = ingest_windows(
            client=client,
            sink=sink,
            tickers=[("PETR4", "B", "01/09/2026 10:00:00", "01/09/2026 16:00:00")],
            inactivity_timeout=0.3,
            stop_client=False,
        )
        # The dispatcher thread must still be pumping after a non-stopping run.
        assert client._dispatcher._thread is not None
        assert client._dispatcher._thread.is_alive()

        second = ingest_windows(
            client=client,
            sink=sink,
            tickers=[("PETR4", "B", "02/09/2026 10:00:00", "02/09/2026 16:00:00")],
            inactivity_timeout=0.3,
        )
        responder.stop()
    sink.close()

    assert first.trades_written == 1
    assert second.trades_written == 1

    conn = sqlite3.connect(tmp_path / "twice.db")
    try:
        count = conn.execute('SELECT COUNT(*) FROM "trades"').fetchone()[0]
    finally:
        conn.close()
    assert count == 2, "handlers must be removed between runs (no duplicate writes)"


def test_ingest_windows_validates_input(tmp_path: Path) -> None:
    backend = _make_backend()
    client = ProfitClient(mode="market_data", backend=backend, **_FAKE_CREDS)
    sink = SqliteSink(db_url=str(tmp_path / "validate.db"), batch_size=10)

    with client:
        with pytest.raises(ValueError, match="at least one"):
            ingest_windows(client=client, sink=sink, tickers=[])
        with pytest.raises(ValueError, match="Invalid window"):
            ingest_windows(
                client=client,
                sink=sink,
                tickers=[("PETR4", "B", "2026-09-01", "2026-09-02")],
            )
        with pytest.raises(ValueError, match=r"end .* precedes start"):
            ingest_windows(
                client=client,
                sink=sink,
                tickers=[("PETR4", "B", "02/09/2026 10:00:00", "01/09/2026 10:00:00")],
            )
        with pytest.raises(ValueError, match="must be"):
            ingest_windows(client=client, sink=sink, tickers=[("PETR4", "B", "02/09/2026")])
    sink.close()
    assert backend.history_trade_requests == []
