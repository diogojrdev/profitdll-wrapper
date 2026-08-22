"""Event dispatcher: Thread-safe queue processing bridge between ProfitDLL and user code."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread
from typing import TYPE_CHECKING, ClassVar

from profitdll_wrapper._bindings.enums import SystemHealthState
from profitdll_wrapper._types.messages import AdjustHistory, InvalidTickerEvent
from profitdll_wrapper._types.models import (
    Account,
    AssetInfo,
    DailyCandle,
    Order,
    Position,
    PriceBookSnapshot,
    PriceLevel,
    TickerStateChange,
    Trade,
    TradingMessageResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from profitdll_wrapper._bindings.functions import Backend

logger = logging.getLogger("profitdll_wrapper.events")

# Queue shutdown sentinel object
_STOP = object()

# How long stop() waits for the dispatch thread before giving up (seconds).
_JOIN_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    """Error event wrapping an exception raised by a user event handler.

    Delivered to handlers registered on Event.ERROR.
    """

    exception: BaseException
    context: str = ""


class EventDispatcher:
    """Drains thread-safe event queue and invokes registered user event handlers."""

    def __init__(self, backend: Backend) -> None:
        self._backend = backend
        self._queue: Queue[object] = Queue()
        self._handlers: dict[str, list[Callable[[object], None]]] = {}
        self._thread: Thread | None = None
        self._stop_evt: Event = Event()
        self._running = False

    def on(self, event: str) -> Callable[[Callable[..., None]], None]:
        """Decorator for registering an event handler callback."""

        def _decorator(fn: Callable[..., None]) -> None:
            self._handlers.setdefault(event, []).append(fn)

        return _decorator

    def add_handler(self, event: str, fn: Callable[..., None]) -> None:
        """Imperative method to add an event handler callback."""
        self._handlers.setdefault(event, []).append(fn)

    def enqueue_trade(self, trade: Trade) -> None:
        """Enqueues a trade event (thread-safe)."""
        self._queue.put(trade)

    def enqueue_price_level(self, level: PriceLevel) -> None:
        """Enqueues a price depth level update event (thread-safe)."""
        self._queue.put(level)

    def enqueue_price_snapshot(self, snapshot: PriceBookSnapshot) -> None:
        """Enqueues a full price book snapshot event (thread-safe)."""
        self._queue.put(snapshot)

    def enqueue_daily(self, candle: DailyCandle) -> None:
        """Enqueues a daily candle summary event (thread-safe)."""
        self._queue.put(candle)

    def enqueue_order(self, order: Order) -> None:
        """Enqueues an order status update event (thread-safe)."""
        self._queue.put(order)

    def enqueue_position(self, position: Position) -> None:
        """Enqueues a position update event (thread-safe)."""
        self._queue.put(position)

    def enqueue_account(self, account: Account) -> None:
        """Enqueues an account detail update event (thread-safe)."""
        self._queue.put(account)

    def enqueue_trading_message(self, msg: TradingMessageResult) -> None:
        """Enqueues a trading message / risk notification event (thread-safe)."""
        self._queue.put(msg)

    def enqueue_asset_info(self, info: AssetInfo) -> None:
        """Enqueues an asset specification info event (thread-safe)."""
        self._queue.put(info)

    def enqueue_ticker_state(self, change: TickerStateChange) -> None:
        """Enqueues a ticker trading state change event (thread-safe)."""
        self._queue.put(change)

    def enqueue_health_change(self, state: SystemHealthState) -> None:
        """Enqueues a system health state change event (thread-safe)."""
        self._queue.put(state)

    def enqueue_historical_trade(self, trade: Trade) -> None:
        """Enqueues a historical trade event (thread-safe)."""
        self._queue.put(("HISTORICAL_TRADE", trade))

    def enqueue_adjust_history(self, adjust: AdjustHistory) -> None:
        """Enqueues a corporate action / adjustment history event (thread-safe)."""
        self._queue.put(adjust)

    def enqueue_invalid_ticker(self, event: InvalidTickerEvent) -> None:
        """Enqueues an invalid ticker / exchange event (thread-safe)."""
        self._queue.put(event)

    def start(self) -> None:
        """Starts background dispatcher daemon thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = Thread(target=self._loop, name="profitdll-dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signals background thread to stop and waits for completion.

        Joins the dispatcher thread with a bounded timeout. If a user event
        handler is still running when the timeout elapses, the orphan thread is
        logged as a warning (it is a daemon, so it will not block process exit)
        rather than being silently abandoned. Idempotent: safe to call multiple
        times (e.g. once from the connect() failure path and again from __exit__).
        """
        self._running = False
        self._stop_evt.set()
        self._queue.put(_STOP)

        thread = self._thread
        if thread is not None and thread != threading.current_thread():
            self._thread = None
            thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
            if thread.is_alive():
                logger.warning(
                    "profitdll-dispatcher thread did not stop within %ss; "
                    "a user event handler may still be running. The thread is a "
                    "daemon and will not block process exit.",
                    _JOIN_TIMEOUT_SECONDS,
                )

    def run(self) -> None:
        """Blocks calling thread until stop() or KeyboardInterrupt."""
        self.start()
        try:
            while self._running:
                self._stop_evt.wait(timeout=0.2)
        except KeyboardInterrupt:
            self.stop()
            raise

    def _loop(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except Empty:
                continue
            if item is _STOP:
                break
            self._dispatch(item)

    _EVENT_BY_TYPE: ClassVar[dict[type, str]] = {
        Trade: "TRADE",
        PriceLevel: "PRICE_LEVEL",
        PriceBookSnapshot: "PRICE_SNAPSHOT",
        DailyCandle: "DAILY",
        Order: "ORDER",
        Position: "POSITION",
        Account: "ACCOUNT",
        TradingMessageResult: "TRADING_MESSAGE",
        AssetInfo: "ASSET_INFO",
        TickerStateChange: "TICKER_STATE",
        SystemHealthState: "HEALTH_CHANGE",
        AdjustHistory: "ADJUST_HISTORY",
        InvalidTickerEvent: "INVALID_TICKER",
    }

    def _dispatch(self, item: object) -> None:
        """Dispatches single event item to registered handlers."""
        if isinstance(item, ErrorEvent):
            self._invoke_handlers("ERROR", item)
            return

        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
            self._invoke_handlers(item[0], item[1])
            return

        event_name = self._EVENT_BY_TYPE.get(type(item))
        if event_name is None:
            logger.debug("Unhandled event (no route): %r", item)
            return
        self._invoke_handlers(event_name, item)

    def _invoke_handlers(self, event_name: str, item: object) -> None:
        """Executes handlers registered for event_name, catching user exceptions safely."""
        handlers = self._handlers.get(event_name, [])
        for fn in handlers:
            try:
                fn(item)
            except Exception as exc:
                logger.exception("Handler for %s failed: %s", event_name, fn)
                if isinstance(item, ErrorEvent):
                    continue
                err_handlers = self._handlers.get("ERROR", [])
                for ef in err_handlers:
                    try:
                        ef(ErrorEvent(exception=exc, context=f"{event_name} handler"))
                    except Exception:
                        logger.exception("Error handler failed")

    def __enter__(self) -> EventDispatcher:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()


__all__ = ["ErrorEvent", "EventDispatcher"]
