"""profitdll-wrapper — Idiomatic Python wrapper for ProfitDLL (Nelogica).

Provides a typed, safe Python API over Nelogica's native C/Delphi DLL (ProfitDLL),
handling stdcall conventions, raw pointers, and thread-safe callback dispatching.

Layered Architecture:
* profitdll_wrapper           — Public API (ProfitClient, Event, Trade, Order, etc.).
* profitdll_wrapper._events   — Dispatcher: DLL callbacks -> thread-safe queue -> handlers.
* profitdll_wrapper._types    — ctypes mappings, dataclasses, enums, PWideChar helpers.
* profitdll_wrapper._bindings — Pure ctypes loader, function signatures, low-level bindings.

Quickstart:

    from profitdll_wrapper import Event, ProfitClient

    with ProfitClient(
        activation_key="...", user="...", password="...", mode="market_data"
    ) as client:
        client.subscribe("WDOFUT", exchange="B")

        @client.on(Event.TRADE)
        def on_trade(trade):
            print(f"{trade.asset.ticker} {trade.price:.2f} x{trade.quantity}")

        client.run()
"""

from __future__ import annotations

import logging

from profitdll_wrapper._bindings.enums import (
    AccountType,
    BookSide,
    BookUpdateType,
    ExchangeCode,
    OrderSide,
    OrderStatus,
    OrderType,
    SystemHealthState,
    TradingMessageResultCode,
)
from profitdll_wrapper._bindings.errors import (
    AuthError,
    HistoryPeriodLimitError,
    InvalidArgumentError,
    NLCode,
    PlatformNotSupportedError,
    ProfitAPIError,
    ProfitConnectionError,
    ProfitError,
    ServerStateError,
)
from profitdll_wrapper._events.dispatcher import EventDispatcher
from profitdll_wrapper._timeutils import B3_TZ, b3_local_to_utc
from profitdll_wrapper._types.messages import (
    AdjustHistory,
    AssetInfo,
    HistoryProgress,
    InvalidTickerEvent,
    TickerStateChange,
    TradingMessageResult,
)
from profitdll_wrapper._types.models import (
    Account,
    AssetId,
    DailyCandle,
    Order,
    Position,
    PriceBookSnapshot,
    PriceLevel,
    Trade,
)
from profitdll_wrapper.client import Event, Mode, ProfitClient

# Library logging convention (PEP 282 / logging HOWTO): attach a NullHandler
# so applications without logging configuration see no spurious output.
logging.getLogger("profitdll_wrapper").addHandler(logging.NullHandler())

__version__ = "0.4.0"

__all__ = [
    "B3_TZ",
    "Account",
    "AccountType",
    "AdjustHistory",
    "AssetId",
    "AssetInfo",
    "AuthError",
    "BookSide",
    "BookUpdateType",
    "DailyCandle",
    "Event",
    "EventDispatcher",
    "ExchangeCode",
    "HistoryPeriodLimitError",
    "HistoryProgress",
    "InvalidArgumentError",
    "InvalidTickerEvent",
    "Mode",
    "NLCode",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PlatformNotSupportedError",
    "Position",
    "PriceBookSnapshot",
    "PriceLevel",
    "ProfitAPIError",
    "ProfitClient",
    "ProfitConnectionError",
    "ProfitError",
    "ServerStateError",
    "SystemHealthState",
    "TickerStateChange",
    "Trade",
    "TradingMessageResult",
    "TradingMessageResultCode",
    "__version__",
    "b3_local_to_utc",
]
