"""Ingestion runner: wires ProfitDLL events into a sink.

The DLL streams historical trades asynchronously via callbacks. Since v0.4.0
the runner also consumes the vendor progress callback (``TProgressCallback``,
registered at initialization — see the manual's ``GetHistoryTrades`` entry:
"The TProgressCallback will return the download progress (from 1 to 100)"),
so per-asset completion is detected by ``progress >= 100`` instead of being
guessed from silence. Timeouts remain as fallbacks for requests the DLL never
answers:

* ``first_event_timeout`` — grace for the FIRST event (trade or progress) of a
  request; expiring marks the ticker ``empty`` with a warning instead of
  silently guessing "complete".
* ``inactivity_timeout`` — silence AFTER events started flowing.
* ``max_timeout`` / ``request_timeout`` — hard ceilings.

Two runners are provided:

* :func:`ingest_history` — legacy contract: ONE shared window for all tickers,
  all requests fired up front. Safe because every late answer falls inside the
  same window. Do NOT stack different windows in one run: the historical-trade
  event carries no window, so late responses cannot be attributed to a request
  (real production incident: one day's tape recorded with another day's
  trades).
* :func:`ingest_windows` — one request in flight at a time, each with its own
  window; trades outside the current request's window are discarded and
  counted, and completion is driven by the progress callback.

Usage::

    from profitdll_wrapper.ingest import create_sink, ingest_history, ingest_windows

    sink = create_sink("sqlite", db_url="profit.db")
    with ProfitClient(...) as client:
        stats = ingest_history(
            client=client, sink=sink,
            tickers=[("VALE3", "B")],
            start_date="01/01/2026 09:00:00",
            end_date="31/01/2026 18:00:00",
        )
    sink.close()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from profitdll_wrapper._types.messages import HistoryProgress, InvalidTickerEvent
from profitdll_wrapper._types.models import Trade
from profitdll_wrapper.client import Event

if TYPE_CHECKING:
    from collections.abc import Callable

    from profitdll_wrapper.ingest.sink import DataSink

logger = logging.getLogger("profitdll_wrapper.ingest")

# Polling interval (s) for the inactivity watchdog and per-request waits.
_WATCHDOG_INTERVAL = 0.2

# DLL request/trade date format ("mm = minute, MM = month" per the manual).
_DLL_DATE_FORMAT = "%d/%m/%Y %H:%M:%S"


@runtime_checkable
class IngestClient(Protocol):
    """Minimal client surface required by the ingest runners.

    ``ProfitClient`` satisfies this protocol; tests can supply any object
    implementing these four methods. ``off`` and ``interrupt_run`` are used
    opportunistically when present (``ProfitClient`` provides both since
    v0.4.0): handler removal avoids duplicate writes across runs, and
    ``interrupt_run`` keeps the session alive with ``stop_client=False``.
    """

    def on(self, event: Event | str) -> Callable[[Callable[..., object]], object]: ...

    def get_history_trades(
        self, ticker: str, start_date: str, end_date: str, *, exchange: str = "B"
    ) -> None: ...

    def run(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(slots=True)
class TickerStats:
    """Per-ticker ingestion counters.

    Attributes:
        ticker: Ticker symbol.
        exchange: Exchange code.
        trades_written: Trades persisted via the sink.
        candles_written: Daily candles persisted via the sink.
        invalid: DLL rejected the ticker/exchange (INVALID_TICKER).
        completed_by_progress: Request finished by the progress callback
            reaching 100 (real completion signal) rather than a timeout.
        empty: No trade AND no progress event ever arrived for this ticker —
            the request likely never drained from the DLL queue. Distinct from
            a legitimately quiet day (which still emits progress events).
        timed_out: A hard ceiling (``request_timeout``/``max_timeout``) ended
            this request before completion.
        discarded_out_of_window: Trades of the current ticker rejected for
            falling outside the request window (multi-window defense).
        discarded_stray: Trades of a different ticker rejected while another
            request was in flight (late response from a previous request).
    """

    ticker: str
    exchange: str
    trades_written: int = 0
    candles_written: int = 0
    invalid: bool = False
    completed_by_progress: bool = False
    empty: bool = False
    timed_out: bool = False
    discarded_out_of_window: int = 0
    discarded_stray: int = 0

    @property
    def total_written(self) -> int:
        return self.trades_written + self.candles_written


@dataclass(slots=True)
class IngestStats:
    """Aggregate result of an ingest run."""

    tickers: list[TickerStats] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def trades_written(self) -> int:
        return sum(t.trades_written for t in self.tickers)

    @property
    def candles_written(self) -> int:
        return sum(t.candles_written for t in self.tickers)

    def for_ticker(self, ticker: str, exchange: str) -> TickerStats | None:
        for ts in self.tickers:
            if ts.ticker == ticker and ts.exchange == exchange:
                return ts
        return None


# Extra seconds granted to the client thread beyond max_timeout before a
# forced stop, and how long to wait for the watchdog thread to unwind.
_JOIN_MARGIN_SECONDS = 5.0
_WATCHDOG_JOIN_SECONDS = 2.0


def _remove_handler(client: IngestClient, event: Event, fn: Callable[..., None]) -> None:
    """Removes a runner-registered handler when the client supports ``off``."""
    off = getattr(client, "off", None)
    if callable(off):
        off(event, fn)


def _end_run(client: IngestClient, *, stop_client: bool) -> None:
    """Ends the run's wait loop, optionally keeping the session alive.

    ``stop_client=False`` unblocks any ``run()`` waiter without stopping the
    dispatcher thread, so the session stays usable for another run; clients
    without ``interrupt_run`` fall back to ``stop()``.
    """
    if stop_client:
        client.stop()
        return
    interrupt = getattr(client, "interrupt_run", None)
    if callable(interrupt):
        interrupt()
    else:  # pragma: no cover - legacy duck-typed clients
        client.stop()


def ingest_history(
    *,
    client: IngestClient,
    sink: DataSink,
    tickers: list[tuple[str, str]],
    start_date: str,
    end_date: str,
    data_types: list[str] | None = None,
    inactivity_timeout: float = 15.0,
    max_timeout: float = 300.0,
    want_candles: bool | None = None,
    first_event_timeout: float = 60.0,
    stop_client: bool = True,
) -> IngestStats:
    """Requests historical data for each ticker and persists it via ``sink``.

    Contract: ONE window per run. All requests share ``start_date``/``end_date``
    and are fired up front; completion is per-ticker, driven by the DLL's
    progress callback reaching 100 (with a short inactivity drain) and falling
    back to inactivity/first-event timeouts. Stacking runs with different
    windows on the same session is not supported here — late DLL responses
    carry no window attribution and would contaminate the tapes; use
    :func:`ingest_windows` for per-ticker windows.

    Args:
        client: A connected (or connectable) :class:`ProfitClient`.
        sink: Destination :class:`DataSink`.
        tickers: List of ``(ticker, exchange)`` pairs to extract.
        start_date: Start of the interval, ``"DD/MM/YYYY HH:MM:SS"``.
        end_date: End of the interval, same format.
        data_types: Subset of ``{"trades", "candles"}`` to persist. Defaults to
            ``["trades"]``. If ``want_candles`` is provided it takes precedence
            for backward-compatibility.
        inactivity_timeout: Seconds of silence (after events started) before a
            ticker's stream is assumed complete.
        max_timeout: Hard upper bound for the whole run.
        want_candles: Deprecated; prefer ``data_types``.
        first_event_timeout: Grace for the FIRST event (trade, candle or
            progress) per ticker. A ticker that never receives anything is
            flagged ``empty`` with a warning instead of being silently marked
            complete — "queued in the DLL" is not "finished".
        stop_client: When True (default) the client's run loop is stopped at
            the end (same as previous versions). False keeps the session
            usable for another run on the same client.

    Returns:
        :class:`IngestStats` with per-ticker counts and elapsed time.
    """
    if not tickers:
        msg = "ingest_history requires at least one (ticker, exchange) pair."
        raise ValueError(msg)

    # Normalize data_types into explicit flags.
    if want_candles is not None:
        types = {"trades": True, "candles": bool(want_candles)}
    else:
        wanted = set(data_types or ["trades"])
        unknown = wanted - {"trades", "candles"}
        if unknown:
            msg = f"Unknown data types {sorted(unknown)}; expected 'trades' and/or 'candles'."
            raise ValueError(msg)
        types = {"trades": "trades" in wanted, "candles": "candles" in wanted}

    stats_by_key: dict[tuple[str, str], TickerStats] = {
        (t, e): TickerStats(ticker=t, exchange=e) for t, e in tickers
    }
    # Last-activity timestamps per ticker, used by the inactivity watchdog;
    # first-activity stays None until the DLL delivers anything for the ticker.
    run_started = time.monotonic()
    last_activity: dict[tuple[str, str], float] = {k: run_started for k in stats_by_key}
    first_activity: dict[tuple[str, str], float | None] = {k: None for k in stats_by_key}
    # Tickers whose progress callback already reached 100 (request complete).
    progress_done: set[tuple[str, str]] = set()
    # Tickers that have already been considered "done" by the watchdog.
    completed: set[tuple[str, str]] = set()
    invalid_tickers: set[tuple[str, str]] = set()
    state_lock = threading.Lock()

    def _touch(ticker: str, exchange: str) -> None:
        now = time.monotonic()
        with state_lock:
            last_activity[(ticker, exchange)] = now
            if first_activity.get((ticker, exchange)) is None:
                first_activity[(ticker, exchange)] = now

    # ------------------------------------------------------------------ #
    # Event handlers (run on the dispatcher thread)
    # ------------------------------------------------------------------ #
    def on_historical_trade(trade: Trade) -> None:
        key = (trade.asset.ticker, trade.asset.exchange)
        sink.write_trade(trade)
        with state_lock:
            ts = stats_by_key.get(key)
            if ts is not None:
                ts.trades_written += 1
        _touch(trade.asset.ticker, trade.asset.exchange)

    def on_daily(candle: object) -> None:
        # DailyCandle carries the asset identifier.
        asset = getattr(candle, "asset", None)
        if asset is None:
            return
        ticker = getattr(asset, "ticker", "")
        exchange = getattr(asset, "exchange", "")
        sink.write_candle(candle)  # type: ignore[arg-type]
        with state_lock:
            ts = stats_by_key.get((ticker, exchange))
            if ts is not None:
                ts.candles_written += 1
        _touch(ticker, exchange)

    def on_progress(evt: HistoryProgress) -> None:
        key = (evt.asset.ticker, evt.asset.exchange)
        with state_lock:
            if key not in stats_by_key:
                return
            if evt.progress >= 100:
                progress_done.add(key)
        # Progress is DLL activity: it proves the request is being served and
        # resets the inactivity clock (drain window after the 100).
        _touch(*key)

    def on_invalid_ticker(evt: InvalidTickerEvent) -> None:
        key = (evt.asset.ticker, evt.asset.exchange)
        logger.warning(
            "Invalid ticker %s on exchange %s; skipping.", evt.asset.ticker, evt.asset.exchange
        )
        with state_lock:
            invalid_tickers.add(key)
            ts = stats_by_key.get(key)
            if ts is not None:
                ts.invalid = True

    client.on(Event.HISTORICAL_TRADE)(on_historical_trade)
    if types["candles"]:
        client.on(Event.DAILY)(on_daily)
    client.on(Event.HISTORY_PROGRESS)(on_progress)
    client.on(Event.INVALID_TICKER)(on_invalid_ticker)

    # Issue the historical trade requests up front.
    if types["trades"]:
        for ticker, exchange in tickers:
            try:
                client.get_history_trades(ticker, start_date, end_date, exchange=exchange)
                logger.info("Requested trade history for %s (%s).", ticker, exchange)
            except Exception:
                logger.exception("Failed to request trade history for %s (%s).", ticker, exchange)

    # ------------------------------------------------------------------ #
    # Inactivity watchdog: end the run once all tickers go quiet.
    # ------------------------------------------------------------------ #
    def watchdog() -> None:
        while True:
            time.sleep(_WATCHDOG_INTERVAL)
            now = time.monotonic()
            with state_lock:
                pending = []
                for key, last in last_activity.items():
                    if key in completed or key in invalid_tickers:
                        continue
                    ts = stats_by_key.get(key)
                    first = first_activity.get(key)
                    if first is None:
                        # Nothing received yet: use the longer first-event grace
                        # so a queued request is not mistaken for a finished one.
                        if now - run_started >= first_event_timeout:
                            completed.add(key)
                            if ts is not None:
                                ts.empty = True
                            logger.warning(
                                "Ticker %s (%s): no trades, candles or progress within "
                                "%.1fs of the request — marking empty (response may "
                                "never have drained from the DLL queue).",
                                key[0],
                                key[1],
                                first_event_timeout,
                            )
                        else:
                            pending.append(key)
                        continue
                    if key in progress_done:
                        # Request reported 100: complete after a short drain so
                        # trades still in flight are not cut off.
                        if now - last >= inactivity_timeout:
                            completed.add(key)
                            if ts is not None:
                                ts.completed_by_progress = True
                                logger.info(
                                    "Ticker %s (%s): progress reached 100; complete.",
                                    key[0],
                                    key[1],
                                )
                        else:
                            pending.append(key)
                        continue
                    if now - last >= inactivity_timeout:
                        completed.add(key)
                        logger.info(
                            "Ticker %s (%s): stream idle for %.1fs, assuming complete "
                            "(no progress signal observed).",
                            key[0],
                            key[1],
                            inactivity_timeout,
                        )
                    else:
                        pending.append(key)
                done = (not pending) or (now - run_started >= max_timeout)

            if done:
                logger.info("All tickers complete (or max_timeout reached); ending run.")
                try:
                    _end_run(client, stop_client=stop_client)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Error stopping client from watchdog.")
                return

    # Run the client on a background thread; the watchdog ends it.
    client_thread = threading.Thread(target=client.run, name="profitdll-ingest-run", daemon=True)
    watchdog_thread = threading.Thread(
        target=watchdog, name="profitdll-ingest-watchdog", daemon=True
    )

    start_wall = time.monotonic()
    client_thread.start()
    watchdog_thread.start()

    try:
        client_thread.join(timeout=max_timeout + _JOIN_MARGIN_SECONDS)
        if client_thread.is_alive():  # pragma: no cover - defensive
            logger.warning("Client thread did not stop within max_timeout; forcing stop.")
            try:
                client.stop()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Error forcing client stop.")
            client_thread.join(timeout=_JOIN_MARGIN_SECONDS)

        watchdog_thread.join(timeout=_WATCHDOG_JOIN_SECONDS)
    finally:
        # Handlers registered by this run must not leak into the next one:
        # without removal, a second ingest on the same client duplicates writes.
        _remove_handler(client, Event.HISTORICAL_TRADE, on_historical_trade)
        if types["candles"]:
            _remove_handler(client, Event.DAILY, on_daily)
        _remove_handler(client, Event.HISTORY_PROGRESS, on_progress)
        _remove_handler(client, Event.INVALID_TICKER, on_invalid_ticker)

    # Flush whatever remains buffered in the sink.
    sink.flush()

    stats = IngestStats(
        tickers=[stats_by_key[k] for k in tickers],
        elapsed_seconds=round(time.monotonic() - start_wall, 3),
    )
    logger.info(
        "Ingestion finished in %.2fs: %d trades, %d candles across %d ticker(s).",
        stats.elapsed_seconds,
        stats.trades_written,
        stats.candles_written,
        len(stats.tickers),
    )
    return stats


def ingest_windows(
    *,
    client: IngestClient,
    sink: DataSink,
    tickers: list[tuple[str, str, str, str]],
    first_event_timeout: float = 60.0,
    inactivity_timeout: float = 15.0,
    request_timeout: float = 300.0,
    max_timeout: float = 1800.0,
    stop_client: bool = True,
) -> IngestStats:
    """Downloads historical trades serially, one window per request.

    Each entry in ``tickers`` is ``(ticker, exchange, start_date, end_date)``
    with dates in ``"DD/MM/YYYY HH:MM:SS"`` (B3 local, same domain the DLL
    reports on trade timestamps — no timezone conversion happens here; convert
    at the sink if needed). Exactly ONE request is in flight at a time: the
    next is only issued after the current one completes, so every answer is
    attributable to its request — late responses from previous requests are
    discarded and counted (``discarded_stray``), and trades of the current
    ticker outside its window are dropped too (``discarded_out_of_window``).

    Completion of each request is primarily the vendor progress callback
    reaching 100 (``TProgressCallback``, registered at initialization),
    confirmed by a short inactivity drain; fallbacks are the first-event
    grace and the inactivity timeout. Unlike :func:`ingest_history`, this
    runner only handles trades (daily candles have no per-window semantics).

    The function blocks the calling thread (events are still delivered on the
    dispatcher thread) and never raises on per-request failures: timeouts and
    invalid tickers are reported through :class:`TickerStats` (``timed_out``,
    ``empty``, ``invalid``) for the caller to act on.

    Args:
        client: A connected :class:`ProfitClient`.
        sink: Destination :class:`DataSink`.
        tickers: ``(ticker, exchange, start, end)`` requests, in execution
            order. Duplicate tickers with different windows are allowed.
        first_event_timeout: Grace for the FIRST event (trade or progress) of
            each request; expiring marks it ``empty`` with a warning.
        inactivity_timeout: Silence after events started (also the drain window
            applied after progress reaches 100).
        request_timeout: Hard ceiling per request.
        max_timeout: Hard ceiling for the whole run; remaining requests are
            marked ``timed_out`` and skipped when it is exceeded.
        stop_client: When True (default) the client's run loop is stopped at
            the end. False keeps the session usable for another run.

    Returns:
        :class:`IngestStats` with one :class:`TickerStats` per request.
    """
    if not tickers:
        msg = "ingest_windows requires at least one (ticker, exchange, start, end) entry."
        raise ValueError(msg)

    requests: list[tuple[str, str, str, str, datetime, datetime]] = []
    for entry in tickers:
        if len(entry) != 4:
            msg = (
                "ingest_windows entries must be (ticker, exchange, start_date, end_date) "
                f"with dates as {_DLL_DATE_FORMAT!r} strings; got {entry!r}."
            )
            raise ValueError(msg)
        ticker, exchange, start_s, end_s = entry
        try:
            start_dt = datetime.strptime(start_s, _DLL_DATE_FORMAT)
            end_dt = datetime.strptime(end_s, _DLL_DATE_FORMAT)
        except ValueError as exc:
            msg = (
                f"Invalid window for {ticker!r} ({exchange!r}): dates must be "
                f"{_DLL_DATE_FORMAT!r} strings (got start={start_s!r}, end={end_s!r})."
            )
            raise ValueError(msg) from exc
        if end_dt < start_dt:
            msg = f"Invalid window for {ticker!r} ({exchange!r}): end {end_s!r} precedes start {start_s!r}."
            raise ValueError(msg)
        requests.append((ticker, exchange, start_s, end_s, start_dt, end_dt))

    state_lock = threading.Lock()
    # State of the request currently in flight (guarded by state_lock).
    current_key: tuple[str, str] | None = None
    current_stats: TickerStats | None = None
    current_start: datetime | None = None
    current_end: datetime | None = None
    requested_at = 0.0
    first_event_at: float | None = None
    last_event_at: float | None = None
    progress = 0
    invalid = False
    logged_drop_reasons: set[str] = set()
    gap_strays = 0

    def _note_event() -> None:
        nonlocal first_event_at, last_event_at
        now = time.monotonic()
        last_event_at = now
        if first_event_at is None:
            first_event_at = now

    def on_historical_trade(trade: Trade) -> None:
        nonlocal gap_strays
        key = (trade.asset.ticker, trade.asset.exchange)
        with state_lock:
            stats = current_stats
            start, end = current_start, current_end
            if key != current_key or stats is None:
                # Late answer of a previous request (or unsolicited trade):
                # keep it OUT of the current tape and count it.
                if stats is None:
                    gap_strays += 1
                    logger.warning(
                        "Stray historical trade ignored (no request in flight): %s:%s.",
                        key[0],
                        key[1],
                    )
                    return
                stats.discarded_stray += 1
                if "stray" not in logged_drop_reasons:
                    logged_drop_reasons.add("stray")
                    logger.warning(
                        "Stray historical trade(s) for %s:%s ignored — late response of a "
                        "previous request (counted in discarded_stray).",
                        key[0],
                        key[1],
                    )
                return
        assert start is not None and end is not None
        ts = trade.timestamp
        if not (start <= ts <= end):
            # Defense: trade of the right ticker but outside this window.
            with state_lock:
                stats.discarded_out_of_window += 1
                if "out_of_window" not in logged_drop_reasons:
                    logged_drop_reasons.add("out_of_window")
                    logger.warning(
                        "Trade(s) of %s:%s outside window %s..%s discarded (counted in "
                        "discarded_out_of_window).",
                        key[0],
                        key[1],
                        start.strftime(_DLL_DATE_FORMAT),
                        end.strftime(_DLL_DATE_FORMAT),
                    )
            return
        sink.write_trade(trade)
        with state_lock:
            stats.trades_written += 1
            _note_event()

    def on_progress(evt: HistoryProgress) -> None:
        nonlocal progress
        key = (evt.asset.ticker, evt.asset.exchange)
        with state_lock:
            if key != current_key:
                return
            if evt.progress > progress:
                progress = evt.progress
            _note_event()

    def on_invalid_ticker(evt: InvalidTickerEvent) -> None:
        nonlocal invalid
        key = (evt.asset.ticker, evt.asset.exchange)
        with state_lock:
            if key == current_key:
                invalid = True
                if current_stats is not None:
                    current_stats.invalid = True
        logger.warning(
            "Invalid ticker %s on exchange %s; request will be closed as invalid.",
            evt.asset.ticker,
            evt.asset.exchange,
        )

    client.on(Event.HISTORICAL_TRADE)(on_historical_trade)
    client.on(Event.HISTORY_PROGRESS)(on_progress)
    client.on(Event.INVALID_TICKER)(on_invalid_ticker)

    start_wall = time.monotonic()
    run_deadline = start_wall + max_timeout
    all_stats: list[TickerStats] = []
    try:
        for ticker, exchange, start_s, end_s, start_dt, end_dt in requests:
            stats = TickerStats(ticker=ticker, exchange=exchange)
            all_stats.append(stats)
            if time.monotonic() >= run_deadline:
                stats.timed_out = True
                logger.warning(
                    "Run max_timeout of %.1fs exceeded before %s:%s — request skipped.",
                    max_timeout,
                    ticker,
                    exchange,
                )
                continue

            logger.info(
                "Requesting trade history for %s (%s) %s..%s (one request in flight).",
                ticker,
                exchange,
                start_s,
                end_s,
            )
            with state_lock:
                current_key = (ticker, exchange)
                current_stats = stats
                current_start = start_dt
                current_end = end_dt
                requested_at = time.monotonic()
                first_event_at = None
                last_event_at = None
                progress = 0
                invalid = False
                logged_drop_reasons.clear()

            request_deadline = min(requested_at + request_timeout, run_deadline)
            try:
                client.get_history_trades(ticker, start_s, end_s, exchange=exchange)
            except Exception:
                logger.exception("Failed to request trade history for %s (%s).", ticker, exchange)
                with state_lock:
                    current_key = None
                    current_stats = None
                continue

            # Wait for completion (poll; handlers run on the dispatcher thread).
            reason = ""
            while True:
                time.sleep(_WATCHDOG_INTERVAL)
                now = time.monotonic()
                done = False
                with state_lock:
                    first = first_event_at
                    last = last_event_at
                    if invalid:
                        done, reason = True, "invalid"
                    elif progress >= 100 and last is not None and now - last >= inactivity_timeout:
                        done, reason = True, "progress"
                    elif (
                        first is not None and last is not None and now - last >= inactivity_timeout
                    ):
                        done, reason = True, "idle"
                    elif first is None and now - requested_at >= first_event_timeout:
                        done, reason = True, "empty"
                        stats.empty = True
                    elif now >= request_deadline:
                        done, reason = True, "timeout"
                        stats.timed_out = True
                if done:
                    break

            with state_lock:
                if reason == "progress":
                    stats.completed_by_progress = True
                if reason == "empty":
                    logger.warning(
                        "Ticker %s (%s): no trades or progress within %.1fs of the "
                        "request — marking empty (response may never have drained "
                        "from the DLL queue).",
                        ticker,
                        exchange,
                        first_event_timeout,
                    )
                if reason == "timeout":
                    logger.warning(
                        "Ticker %s (%s): request exceeded %.0fs without completing.",
                        ticker,
                        exchange,
                        request_timeout,
                    )
                note = {
                    "progress": "progress reached 100",
                    "idle": "stream idle",
                    "invalid": "invalid ticker",
                    "empty": "no response",
                    "timeout": "timed out",
                }[reason]
                extras = ""
                if stats.discarded_out_of_window:
                    extras += f", {stats.discarded_out_of_window} out-of-window discarded"
                if stats.discarded_stray:
                    extras += f", {stats.discarded_stray} stray discarded"
                logger.info(
                    "Window %s:%s %s..%s: %d trade(s) — %s%s.",
                    ticker,
                    exchange,
                    start_s,
                    end_s,
                    stats.trades_written,
                    note,
                    extras,
                )
                # Close the request: later trades are strays, never written.
                current_key = None
                current_stats = None
    finally:
        _remove_handler(client, Event.HISTORICAL_TRADE, on_historical_trade)
        _remove_handler(client, Event.HISTORY_PROGRESS, on_progress)
        _remove_handler(client, Event.INVALID_TICKER, on_invalid_ticker)

    if gap_strays:
        logger.info("%d stray trade(s) arrived between requests and were discarded.", gap_strays)

    sink.flush()
    _end_run(client, stop_client=stop_client)

    summary = IngestStats(
        tickers=all_stats,
        elapsed_seconds=round(time.monotonic() - start_wall, 3),
    )
    logger.info(
        "Windows ingestion finished in %.2fs: %d trades across %d request(s).",
        summary.elapsed_seconds,
        summary.trades_written,
        len(summary.tickers),
    )
    return summary


__all__ = ["IngestClient", "IngestStats", "TickerStats", "ingest_history", "ingest_windows"]
