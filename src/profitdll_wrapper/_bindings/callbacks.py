"""ctypes callback function types (stdcall via WINFUNCTYPE).

Defines callback signatures invoked by ProfitDLL. The recommended path is V2
(TTradeCallbackV2), which receives an opaque trade pointer translated synchronously
via TranslateTrade.

Critical Rules:
1. Callbacks run on ProfitDLL's internal ConnectorThread.
2. Never invoke requesting API functions (subscribe, place orders) inside callbacks.
3. Accessors (e.g., TranslateTrade) must be called synchronously inside callbacks.
4. Copy any PWideChar string immediately before returning from callback.

Keep-alive: WINFUNCTYPE instances MUST remain referenced while active to prevent
garbage collection crashes. Use keep_alive() to register them in _LIVE_CALLBACKS.
"""

from __future__ import annotations

from ctypes import (
    POINTER,
    c_bool,
    c_double,
    c_int32,
    c_int64,
    c_long,
    c_size_t,
    c_ubyte,
    c_uint,
    c_uint32,
    c_wchar_p,
)

# WINFUNCTYPE (stdcall) only exists on Windows. Aliasing CFUNCTYPE keeps the
# package importable on other platforms (docs, IDEs, CI); actually connecting
# still raises PlatformNotSupportedError in the loader.
try:
    from ctypes import WINFUNCTYPE
except ImportError:
    from ctypes import CFUNCTYPE as WINFUNCTYPE
from typing import TypeVar

from profitdll_wrapper._bindings.structures import (
    TAssetID,
    TConnectorAccountIdentifier,
    TConnectorAssetIdentifier,
    TConnectorAssetIdentifierSafe,
    TConnectorOrder,
    TConnectorOrderIdentifier,
    TConnectorTradingMessageResult,
)

# State Callback: (conn_state_type, result) -> None.
# Reports connection, login, routing, market data, and activation states.
TStateCallback = WINFUNCTYPE(None, c_int32, c_int32)

# Progress Callback: (asset_id, progress) -> None.
# Historical-request download progress per asset (0-100 per the TProgressCallback
# docs; GetHistoryTrades documents "from 1 to 100" — 100 means request complete).
TProgressCallback = WINFUNCTYPE(None, TAssetID, c_int32)

# V2 Trade Callback: (asset_id, p_trade, flags) -> None.
# p_trade is an opaque handle (c_size_t) passed to TranslateTrade.
TTradeCallbackV2 = WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)

# Safe Trade History Callback using pointers for ticker/exchange strings.
TConnectorTradeCallback = WINFUNCTYPE(None, TConnectorAssetIdentifierSafe, c_size_t, c_uint)
THistoryTradeCallback = TConnectorTradeCallback

# Price Depth Callback (v4.0.0.31): (asset_id, side, position, update_type) -> None.
# Carries no level data; the handler reads levels via the GetPriceGroup accessor.
TPriceDepthCallback = WINFUNCTYPE(
    None,
    TConnectorAssetIdentifier,
    c_ubyte,  # side (0=Buy, 1=Sell, 254=Both)
    c_int32,  # position
    c_ubyte,  # update_type (0..8)
)

# Legacy Daily Candle Callback: (asset_id, date, OHLCV...) -> None.
TDailyCallback = WINFUNCTYPE(
    None,
    TAssetID,
    c_wchar_p,  # date string "DD/MM/YYYY HH:mm:SS.ZZZ"
    c_double,  # sOpen
    c_double,  # sHigh
    c_double,  # sLow
    c_double,  # sClose
    c_double,  # sVol
    c_double,  # sAjuste
    c_double,  # sMaxLimit
    c_double,  # sMinLimit
    c_double,  # sVolBuyer
    c_double,  # sVolSeller
    c_int32,  # nQtd
    c_int32,  # nTrades
    c_int32,  # nOpenContracts
    c_int32,  # nQtdBuyer
    c_int32,  # nQtdSeller
    c_int32,  # nTradesBuyer
    c_int32,  # nTradesSeller
)

# V2 Order Change Callback (Routing):
TOrderChangeCallbackV2 = WINFUNCTYPE(
    None,
    TAssetID,
    c_int32,  # broker_id
    c_int32,  # quantity
    c_int32,  # traded_quantity
    c_int32,  # leaves_quantity
    c_int32,  # side (1=Buy, 2=Sell)
    c_int32,  # validity
    c_double,  # price
    c_double,  # stop_price
    c_double,  # avg_price
    c_int64,  # profit_id
    c_wchar_p,  # order_type
    c_wchar_p,  # account
    c_wchar_p,  # account_holder
    c_wchar_p,  # cl_ord_id
    c_wchar_p,  # status
    c_wchar_p,  # last_update
    c_wchar_p,  # close_date
    c_wchar_p,  # validity_date
    c_wchar_p,  # text_message
)

# V2 Offer Book Callback (Market Data / Depth):
TOfferBookCallbackV2 = WINFUNCTYPE(
    None,
    TAssetID,
    c_int32,  # action (0=Add, 1=Edit, 2=Delete, 3=DeleteFrom, 4=FullBook)
    c_int32,  # position
    c_int32,  # side (0=Buy, 1=Sell)
    c_int32,  # quantity
    c_int32,  # agent_id
    c_int64,  # offer_id
    c_double,  # price
    c_int32,  # has_price
    c_int32,  # has_quantity
    c_int32,  # has_date
    c_int32,  # has_offer_id
    c_int32,  # has_agent
    c_wchar_p,  # date
    POINTER(c_ubyte),  # p_sell_array
    POINTER(c_ubyte),  # p_buy_array
)

# V1 Order Callback: (order_id) -> None.
TConnectorOrderCallback = WINFUNCTYPE(None, TConnectorOrderIdentifier)

# Asset Position List Callback: (account, asset, last_event) -> None.
TAssetPositionListCallback = WINFUNCTYPE(
    None,
    TConnectorAccountIdentifier,
    TConnectorAssetIdentifier,
    c_int32,
)

# Order History Loaded Callback: (account_id) -> None.
# Fired by SetOrderHistoryCallback when an account's order history finished loading.
TConnectorAccountCallback = WINFUNCTYPE(None, TConnectorAccountIdentifier)

# Enumeration Callbacks:
TConnectorEnumerateOrdersProc = WINFUNCTYPE(c_bool, POINTER(TConnectorOrder), c_long)
TConnectorEnumerateAssetProc = WINFUNCTYPE(c_bool, POINTER(TConnectorAssetIdentifier), c_long)

# Account/Sub-account List Callbacks:
TConnectorBrokerAccountListCallback = WINFUNCTYPE(None, c_int32, c_uint32)
TConnectorBrokerSubAccountListCallback = WINFUNCTYPE(None, TConnectorAccountIdentifier)
TConnectorTradingMessageResultCallback = WINFUNCTYPE(None, POINTER(TConnectorTradingMessageResult))

# V2 Asset Info Callback:
TAssetListInfoCallbackV2 = WINFUNCTYPE(
    None,
    TAssetID,
    c_wchar_p,  # name
    c_wchar_p,  # description
    c_int64,  # min_order_qty
    c_int64,  # max_order_qty
    c_int64,  # lot_size
    c_int32,  # security_type
    c_int32,  # security_subtype
    c_double,  # min_price_increment
    c_double,  # contract_multiplier
    c_wchar_p,  # valid_date
    c_wchar_p,  # isin
    c_wchar_p,  # sector
    c_wchar_p,  # sub_sector
    c_wchar_p,  # segment
)

# Ticker State Change Callback: (asset_id, date, state) -> None.
TChangeStateTicker = WINFUNCTYPE(None, TAssetID, c_wchar_p, c_int32)

# System Health Callback: (state) -> None.
TSystemHealthCallback = WINFUNCTYPE(None, c_int32)

# Corporate Actions / Adjustments Callback:
TAdjustHistoryCallbackV2 = WINFUNCTYPE(
    None,
    TAssetID,
    c_double,  # value
    c_wchar_p,  # adjust_type
    c_wchar_p,  # observation
    c_wchar_p,  # adjust_date
    c_wchar_p,  # deliberated_date
    c_wchar_p,  # payment_date
    c_int32,  # affects_price
)

# Invalid Ticker Callback: (p_asset_id) -> None.
TInvalidTickerCallback = WINFUNCTYPE(None, POINTER(TConnectorAssetIdentifier))

# TConnectorTradeCallback flags:
TC_IS_EDIT: int = 1
TC_LAST_PACKET: int = 2

# Global keep-alive dictionary for active callback function pointers:
_LIVE_CALLBACKS: dict[str, object] = {}


_T = TypeVar("_T")


def keep_alive(name: str, fn: _T) -> _T:
    """Registers callback `fn` under `name` to prevent garbage collection during DLL calls.

    Args:
        name: Stable key identifier (e.g. "state", "trade").
        fn: Callback object created by WINFUNCTYPE.

    Returns:
        The registered callback function instance.
    """
    _LIVE_CALLBACKS[name] = fn
    return fn


__all__ = [
    "TC_IS_EDIT",
    "TC_LAST_PACKET",
    "TAdjustHistoryCallbackV2",
    "TAssetListInfoCallbackV2",
    "TAssetPositionListCallback",
    "TChangeStateTicker",
    "TConnectorAccountCallback",
    "TConnectorBrokerAccountListCallback",
    "TConnectorBrokerSubAccountListCallback",
    "TConnectorEnumerateAssetProc",
    "TConnectorEnumerateOrdersProc",
    "TConnectorOrderCallback",
    "TConnectorTradeCallback",
    "TConnectorTradingMessageResultCallback",
    "TDailyCallback",
    "THistoryTradeCallback",
    "TInvalidTickerCallback",
    "TOfferBookCallbackV2",
    "TOrderChangeCallbackV2",
    "TPriceDepthCallback",
    "TProgressCallback",
    "TStateCallback",
    "TSystemHealthCallback",
    "TTradeCallbackV2",
    "keep_alive",
]
