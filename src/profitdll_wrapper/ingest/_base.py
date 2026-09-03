"""Buffering base class shared by all sinks.

Tick-by-tick history can reach millions of rows per instrument, so per-row
writes are too slow. Concrete sinks accumulate rows in two in-memory buffers
(one for trades, one for daily candles) and flush them in batches of
``batch_size``. Subclasses implement only :meth:`_flush_trades` and
:meth:`_flush_candles`; this class handles counting, threshold checks and
final ``close`` semantics.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from profitdll_wrapper._timeutils import b3_local_to_utc
from profitdll_wrapper._types.messages import DailyCandle
from profitdll_wrapper._types.models import Trade
from profitdll_wrapper.ingest.schema import candle_to_row, trade_to_row

if TYPE_CHECKING:
    from collections.abc import Sequence


class BufferedSink:
    """Base class providing batch buffering for sinks.

    Subclasses MUST call ``super().__init__(...)`` and implement
    :meth:`_flush_trades` and :meth:`_flush_candles`.

    Args:
        batch_size: Number of records buffered before an automatic flush.
        assume_b3_local: When True, naive trade timestamps (the DLL's B3 local
            times) are converted to timezone-aware UTC before persisting, so
            multi-day tapes line up without a per-consumer ``UtcSink``
            subclass. Aware timestamps pass through unchanged. Daily candle
            dates are plain dates and are never converted. Defaults to False
            (legacy behavior: naive values stored as-is).
    """

    def __init__(self, batch_size: int = 500, *, assume_b3_local: bool = False) -> None:
        if batch_size < 1:
            msg = f"batch_size must be >= 1, got {batch_size}"
            raise ValueError(msg)
        self._batch_size = batch_size
        self._assume_b3_local = assume_b3_local
        self._trade_buffer: list[tuple[object, ...]] = []
        self._candle_buffer: list[tuple[object, ...]] = []
        self._closed = False

    # ------------------------------------------------------------------ #
    # Public API consumed by the ingest runner
    # ------------------------------------------------------------------ #
    def write_trade(self, trade: Trade) -> None:
        self._ensure_open()
        if self._assume_b3_local and trade.timestamp.tzinfo is None:
            trade = replace(trade, timestamp=b3_local_to_utc(trade.timestamp))
        self._trade_buffer.append(trade_to_row(trade))
        if len(self._trade_buffer) >= self._batch_size:
            self._flush_trades(self._trade_buffer)
            self._trade_buffer.clear()

    def write_candle(self, candle: DailyCandle) -> None:
        self._ensure_open()
        self._candle_buffer.append(candle_to_row(candle))
        if len(self._candle_buffer) >= self._batch_size:
            self._flush_candles(self._candle_buffer)
            self._candle_buffer.clear()

    def flush(self) -> None:
        if self._trade_buffer:
            self._flush_trades(self._trade_buffer)
            self._trade_buffer.clear()
        if self._candle_buffer:
            self._flush_candles(self._candle_buffer)
            self._candle_buffer.clear()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.flush()
        finally:
            self._closed = True
            self._on_close()

    # ------------------------------------------------------------------ #
    # Hooks for subclasses
    # ------------------------------------------------------------------ #
    def _flush_trades(self, rows: Sequence[tuple[object, ...]]) -> None:
        raise NotImplementedError

    def _flush_candles(self, rows: Sequence[tuple[object, ...]]) -> None:
        raise NotImplementedError

    def _on_close(self) -> None:
        """Optional resource cleanup hook (default: no-op)."""

    def _ensure_open(self) -> None:
        if self._closed:
            msg = "Sink is closed; cannot write more records."
            raise RuntimeError(msg)


__all__ = ["BufferedSink"]
