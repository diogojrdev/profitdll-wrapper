"""Ingestion runner: wires ProfitDLL events into a sink.

The native DLL streams historical trades asynchronously via callbacks and
never emits an explicit "end of history" signal — it simply stops calling
the handler. To turn that into a bounded operation, the runner monitors
record activity and stops the client when no records arrive for
``inactivity_timeout`` seconds (with a hard ``max_timeout`` ceiling).

Usage::

    from profitdll_wrapper.ingest import create_sink, ingest_history

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
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from profitdll_wrapper._types.messages import InvalidTickerEvent
from profitdll_wrapper._types.models import Trade
from profitdll_wrapper.client import Event

if TYPE_CHECKING:
    from collections.abc import Callable

    from profitdll_wrapper.ingest.sink import DataSink

logger = logging.getLogger("profitdll_wrapper.ingest")

# Polling interval (s) for the inactivity watchdog.
_WATCHDOG_INTERVAL = 0.2


@runtime_checkable
class IngestClient(Protocol):
    """Minimal client surface required by :func:`ingest_history`.

    ``ProfitClient`` satisfies this protocol; tests can supply any object
    implementing these four methods.
    """

    def on(self, event: Event | str) -> Callable[[Callable[..., object]], object]: ...

    def get_history_trades(
        self, ticker: str, start_date: str, end_date: str, *, exchange: str = "B"
    ) -> None: ...

    def run(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(slots=True)
class TickerStats:
    """Per-ticker ingestion counters."""

    ticker: str
    exchange: str
    trades_written: int = 0
    candles_written: int = 0
    invalid: bool = False

    @property
    def total_written(self) -> int:
        return self.trades_written + self.candles_written


@dataclass(slots=True)
class IngestStats:
    """Aggregate result of an :func:`ingest_history` run."""

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
) -> IngestStats:
    """Requests historical data for each ticker and persists it via ``sink``.

    Args:
        client: A connected (or connectable) :class:`ProfitClient`.
        sink: Destination :class:`DataSink`.
        tickers: List of ``(ticker, exchange)`` pairs to extract.
        start_date: Start of the interval, ``"DD/MM/YYYY HH:MM:SS"``.
        end_date: End of the interval, same format.
        data_types: Subset of ``{"trades", "candles"}`` to persist. Defaults to
            ``["trades"]``. If ``want_candles`` is provided it takes precedence
            for backward-compatibility.
        inactivity_timeout: Seconds of silence after which a ticker's stream is
            assumed complete.
        max_timeout: Hard upper bound for the whole run.
        want_candles: Deprecated; prefer ``data_types``.

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
    # Last-activity timestamps per ticker, used by the inactivity watchdog.
    last_activity: dict[tuple[str, str], float] = {(t, e): time.monotonic() for t, e in tickers}
    # Tickers that have already been considered "done" by the watchdog.
    completed: set[tuple[str, str]] = set()
    invalid_tickers: set[tuple[str, str]] = set()
    state_lock = threading.Lock()
    run_started = time.monotonic()

    def _touch(ticker: str, exchange: str) -> None:
        with state_lock:
            last_activity[(ticker, exchange)] = time.monotonic()

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
    # Inactivity watchdog: stop the client once all tickers go quiet.
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
                    if now - last >= inactivity_timeout:
                        completed.add(key)
                        logger.info(
                            "Ticker %s (%s): stream idle for %.1fs, assuming complete.",
                            key[0],
                            key[1],
                            inactivity_timeout,
                        )
                    else:
                        pending.append(key)
                done = (not pending) or (now - run_started >= max_timeout)

            if done:
                logger.info("All tickers complete (or max_timeout reached); stopping client.")
                try:
                    client.stop()
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Error stopping client from watchdog.")
                return

    # Run the client on a background thread; the watchdog stops it.
    client_thread = threading.Thread(target=client.run, name="profitdll-ingest-run", daemon=True)
    watchdog_thread = threading.Thread(
        target=watchdog, name="profitdll-ingest-watchdog", daemon=True
    )

    start_wall = time.monotonic()
    client_thread.start()
    watchdog_thread.start()

    client_thread.join(timeout=max_timeout + _JOIN_MARGIN_SECONDS)
    if client_thread.is_alive():  # pragma: no cover - defensive
        logger.warning("Client thread did not stop within max_timeout; forcing stop.")
        try:
            client.stop()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Error forcing client stop.")
        client_thread.join(timeout=_JOIN_MARGIN_SECONDS)

    watchdog_thread.join(timeout=_WATCHDOG_JOIN_SECONDS)

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


__all__ = ["IngestClient", "IngestStats", "TickerStats", "ingest_history"]
