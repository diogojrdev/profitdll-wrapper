"""ProfitDLL native function signatures and Backend Protocol.

The Backend protocol decouples ProfitClient from the physical DLL loading mechanism,
allowing unit tests to run with fake backends without requiring the Windows-only DLL binary.
"""

from __future__ import annotations

import atexit
import contextlib
import ctypes
from ctypes import (
    POINTER,
    byref,
    c_double,
    c_int,
    c_int64,
    c_long,
    c_size_t,
    c_ubyte,
    c_void_p,
    c_wchar_p,
)
from typing import Any, Protocol, runtime_checkable

from profitdll_wrapper._bindings.callbacks import (
    TAdjustHistoryCallbackV2,
    TAssetListInfoCallbackV2,
    TAssetPositionListCallback,
    TChangeStateTicker,
    TConnectorAccountCallback,
    TConnectorEnumerateAssetProc,
    TConnectorOrderCallback,
    TConnectorTradingMessageResultCallback,
    TDailyCallback,
    TInvalidTickerCallback,
    TOfferBookCallbackV2,
    TOrderChangeCallbackV2,
    TPriceDepthCallback,
    TStateCallback,
    TSystemHealthCallback,
    TTradeCallbackV2,
)
from profitdll_wrapper._bindings.errors import NLCode
from profitdll_wrapper._bindings.structures import (
    TConnectorAccountIdentifier,
    TConnectorAccountIdentifierOut,
    TConnectorAssetIdentifier,
    TConnectorCancelAllOrders,
    TConnectorCancelOrder,
    TConnectorCancelOrders,
    TConnectorChangeOrder,
    TConnectorOrderOut,
    TConnectorPriceGroup,
    TConnectorSendOrder,
    TConnectorTrade,
    TConnectorTradingAccountOut,
    TConnectorTradingAccountPosition,
    TConnectorZeroPosition,
)


@runtime_checkable
class Backend(Protocol):
    """Backend boundary protocol covering all exported native ProfitDLL functions."""

    def initialize_login(
        self,
        activation_key: str,
        user: str,
        password: str,
        state_callback: object,
        daily_callback: object,
        order_change_callback: object = None,
    ) -> int: ...

    def initialize_market_login(
        self,
        activation_key: str,
        user: str,
        password: str,
        state_callback: object,
        daily_callback: object,
    ) -> int: ...

    def finalize(self) -> int: ...

    # ---- Trades & Data Feed ---- #
    def subscribe_ticker(self, ticker: str, exchange: str) -> int: ...

    def unsubscribe_ticker(self, ticker: str, exchange: str) -> int: ...

    def set_trade_callback_v2(self, callback: object) -> int: ...

    def translate_trade(self, p_trade: int, out_trade: TConnectorTrade) -> int: ...

    def get_history_trades(self, ticker: str, exchange: str, start: str, end: str) -> int: ...

    def set_history_trade_callback_v2(self, callback: object) -> int: ...

    # ---- Book & Price Depth ---- #
    def subscribe_price_depth(self, asset: TConnectorAssetIdentifier) -> int: ...

    def unsubscribe_price_depth(self, asset: TConnectorAssetIdentifier) -> int: ...

    def set_price_depth_callback(self, callback: object) -> int: ...

    def subscribe_offer_book(self, ticker: str, exchange: str) -> int: ...

    def unsubscribe_offer_book(self, ticker: str, exchange: str) -> int: ...

    def set_offer_book_callback_v2(self, callback: object) -> int: ...

    def get_price_depth_side_count(self, asset: TConnectorAssetIdentifier, side: int) -> int: ...

    def get_price_group(
        self,
        asset: TConnectorAssetIdentifier,
        side: int,
        position: int,
        out_group: TConnectorPriceGroup,
    ) -> int: ...

    def get_theoretical_values(
        self,
        asset: TConnectorAssetIdentifier,
        out_price: c_double,
        out_qty: c_int64,
    ) -> int: ...

    # ---- Routing & Orders ---- #
    def send_order(self, order: TConnectorSendOrder, out_id: c_int64) -> int: ...

    def send_change_order_v2(self, change: TConnectorChangeOrder) -> int: ...

    def send_cancel_order_v2(self, cancel: TConnectorCancelOrder) -> int: ...

    def send_cancel_orders_v2(self, cancel: TConnectorCancelOrders) -> int: ...

    def send_cancel_all_orders(self, cancel: TConnectorCancelAllOrders) -> int: ...

    def send_zero_position_v2(self, zero: TConnectorZeroPosition, out_id: c_int64) -> int: ...

    def get_position_v2(
        self,
        out_pos: TConnectorTradingAccountPosition,
    ) -> int: ...

    def set_order_change_callback_v2(self, callback: object) -> int: ...

    def set_order_callback(self, callback: object) -> int: ...

    def set_order_history_callback(self, callback: object) -> int: ...

    def get_order_details(self, order_out: TConnectorOrderOut) -> int: ...

    def set_asset_position_list_callback(self, callback: object) -> int: ...

    def set_trading_message_result_callback(self, callback: object) -> int: ...

    def request_ticker_info(self, ticker: str, exchange: str) -> int: ...

    def set_asset_list_info_callback_v2(self, callback: object) -> int: ...

    def set_change_state_ticker_callback(self, callback: object) -> int: ...

    # ---- Accounts ---- #
    def get_account_count(self) -> int: ...

    def get_accounts(
        self, start_source: int, start_dest: int, count: int, accounts_out: Any
    ) -> int: ...

    def get_account_details(self, account_out: TConnectorTradingAccountOut) -> int: ...

    def get_sub_account_count(self, master_id: TConnectorAccountIdentifier) -> int: ...

    def get_sub_accounts(
        self,
        master_id: TConnectorAccountIdentifier,
        start_source: int,
        start_dest: int,
        count: int,
        accounts_out: Any,
    ) -> int: ...

    def get_account_count_by_broker(self, broker_id: int) -> int: ...

    def get_accounts_by_broker(
        self, broker_id: int, start_source: int, start_dest: int, count: int, accounts_out: Any
    ) -> int: ...

    # ---- Order History & Enumeration ---- #
    def has_orders_in_interval(
        self, account_id: TConnectorAccountIdentifier, start: Any, end: Any
    ) -> int: ...

    def enumerate_orders_by_interval(
        self,
        account_id: TConnectorAccountIdentifier,
        order_version: int,
        start: Any,
        end: Any,
        param: int,
        callback: object,
    ) -> int: ...

    def enumerate_all_orders(
        self,
        account_id: TConnectorAccountIdentifier,
        order_version: int,
        param: int,
        callback: object,
    ) -> int: ...

    def enumerate_all_position_assets(
        self,
        account_id: TConnectorAccountIdentifier,
        asset_version: int,
        param: int,
        callback: object,
    ) -> int: ...

    # ---- Utilities & Agent Names ---- #
    def get_agent_name_length(self, agent_id: int, short_flag: int) -> int: ...

    def get_agent_name(self, count: int, agent_id: int, pwc_agent: Any, short_flag: int) -> int: ...

    def set_day_trade(self, use_day_trade: int) -> int: ...

    def set_enabled_log_to_debug(self, enabled: int) -> int: ...

    def get_server_clock(
        self,
        dt_date: c_double,
        year: c_int,
        month: c_int,
        day: c_int,
        hour: c_int,
        minute: c_int,
        sec: c_int,
        millisec: c_int,
    ) -> int: ...

    def get_health_status(self, out_state: Any) -> int: ...

    def set_health_callback(self, callback: object) -> int: ...

    def get_last_daily_close(
        self, ticker: str, exchange: str, out_close: Any, adjusted: int
    ) -> int: ...

    def set_enabled_hist_order(self, enabled: int) -> int: ...

    def subscribe_adjust_history(self, ticker: str, exchange: str) -> int: ...

    def unsubscribe_adjust_history(self, ticker: str, exchange: str) -> int: ...

    def set_adjust_history_callback_v2(self, callback: object) -> int: ...

    def set_invalid_ticker_callback(self, callback: object) -> int: ...


def bind(lib: ctypes.WinDLL) -> ctypes.WinDLL:
    """Declares argtypes/restype for every function exported by ProfitDLL on ``lib``.

    Returns ``lib`` itself (now typed) for chaining.
    """

    def _bind_fn(fn_name: str, argtypes: list[Any], restype: Any) -> None:
        fn = getattr(lib, fn_name, None)
        if fn is not None:
            fn.argtypes = argtypes
            fn.restype = restype

    # ----------------------- Initialization ---------------------- #
    _bind_fn(
        "DLLInitializeMarketLogin",
        [
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
            TStateCallback,
            c_wchar_p,
            TDailyCallback,
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
        ],
        c_int,
    )

    _bind_fn(
        "DLLInitializeLogin",
        [
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
            TStateCallback,
            c_wchar_p,
            c_void_p,
            c_wchar_p,
            c_wchar_p,
            TDailyCallback,
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
        ],
        c_int,
    )

    # ----------------------- Finalization ------------------------ #
    _bind_fn("DLLFinalize", [], c_int)

    # ----------------------- Subscribe (trades) ------------------ #
    _bind_fn("SubscribeTicker", [c_wchar_p, c_wchar_p], c_int)
    _bind_fn("UnsubscribeTicker", [c_wchar_p, c_wchar_p], c_int)

    # ----------------------- Callbacks V2 (trades) --------------- #
    _bind_fn("SetTradeCallbackV2", [TTradeCallbackV2], c_int)
    _bind_fn("SetHistoryTradeCallbackV2", [TTradeCallbackV2], c_int)

    # ----------------------- Accessor (trades) ------------------- #
    _bind_fn("TranslateTrade", [c_size_t, POINTER(TConnectorTrade)], c_int)
    _bind_fn("GetHistoryTrades", [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p], c_int)

    # ----------------------- Price Depth (P1) -------------------- #
    _bind_fn("SubscribePriceDepth", [POINTER(TConnectorAssetIdentifier)], c_int)
    _bind_fn("UnsubscribePriceDepth", [POINTER(TConnectorAssetIdentifier)], c_int)
    _bind_fn("SetPriceDepthCallback", [TPriceDepthCallback], c_int)
    _bind_fn("SetOfferBookCallbackV2", [TOfferBookCallbackV2], c_int)
    _bind_fn("SubscribeOfferBook", [c_wchar_p, c_wchar_p], c_int)
    _bind_fn("UnsubscribeOfferBook", [c_wchar_p, c_wchar_p], c_int)
    _bind_fn("GetPriceDepthSideCount", [POINTER(TConnectorAssetIdentifier), c_ubyte], c_int)
    _bind_fn(
        "GetPriceGroup",
        [
            POINTER(TConnectorAssetIdentifier),
            c_ubyte,
            c_int,
            POINTER(TConnectorPriceGroup),
        ],
        c_int,
    )
    _bind_fn(
        "GetTheoreticalValues",
        [
            POINTER(TConnectorAssetIdentifier),
            POINTER(c_double),
            POINTER(c_int64),
        ],
        c_int,
    )

    # ----------------------- Routing / Orders (P2) --------------- #
    _bind_fn("SendOrder", [POINTER(TConnectorSendOrder)], c_int64)
    _bind_fn("SendChangeOrderV2", [POINTER(TConnectorChangeOrder)], c_int)
    _bind_fn("SendCancelOrderV2", [POINTER(TConnectorCancelOrder)], c_int)
    _bind_fn("SendCancelOrdersV2", [POINTER(TConnectorCancelOrders)], c_int)
    _bind_fn("SendCancelAllOrdersV2", [POINTER(TConnectorCancelAllOrders)], c_int)
    _bind_fn("SendZeroPositionV2", [POINTER(TConnectorZeroPosition)], c_int64)
    _bind_fn(
        "SendZeroPosition",
        [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_double],
        c_int64,
    )
    _bind_fn(
        "SendZeroPositionAtMarket", [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p], c_int64
    )
    _bind_fn(
        "SendBuyOrder",
        [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_double, c_int],
        c_int64,
    )
    _bind_fn(
        "SendSellOrder",
        [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_double, c_int],
        c_int64,
    )
    _bind_fn(
        "SendMarketBuyOrder",
        [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_int],
        c_int64,
    )
    _bind_fn(
        "SendMarketSellOrder",
        [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_int],
        c_int64,
    )
    _bind_fn(
        "SendStopBuyOrder",
        [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_double, c_double, c_int],
        c_int64,
    )
    _bind_fn(
        "SendStopSellOrder",
        [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_double, c_double, c_int],
        c_int64,
    )

    _bind_fn("GetPositionV2", [POINTER(TConnectorTradingAccountPosition)], c_int)
    _bind_fn("SetOrderChangeCallbackV2", [TOrderChangeCallbackV2], c_int)
    _bind_fn("SetOrderCallback", [TConnectorOrderCallback], c_int)
    _bind_fn("SetOrderHistoryCallback", [TConnectorAccountCallback], c_int)
    _bind_fn("GetOrderDetails", [POINTER(TConnectorOrderOut)], c_int)
    _bind_fn("SetAssetPositionListCallback", [TAssetPositionListCallback], c_int)
    _bind_fn("SetTradingMessageResultCallback", [TConnectorTradingMessageResultCallback], c_int)
    _bind_fn("RequestTickerInfo", [c_wchar_p, c_wchar_p], c_int)
    _bind_fn("SetAssetListInfoCallbackV2", [TAssetListInfoCallbackV2], c_int)
    _bind_fn("SetChangeStateTickerCallback", [TChangeStateTicker], c_int)

    # --------------------- Accounts & Enumeration ---------------- #
    _bind_fn("GetAccountCount", [], c_int)
    _bind_fn("GetAccounts", [c_int, c_int, c_int, POINTER(TConnectorAccountIdentifierOut)], c_int)
    _bind_fn("GetAccountDetails", [POINTER(TConnectorTradingAccountOut)], c_int)
    _bind_fn("GetSubAccountCount", [POINTER(TConnectorAccountIdentifier)], c_int)
    _bind_fn(
        "GetSubAccounts",
        [
            POINTER(TConnectorAccountIdentifier),
            c_int,
            c_int,
            c_int,
            POINTER(TConnectorAccountIdentifierOut),
        ],
        c_int,
    )
    _bind_fn("GetAccountCountByBroker", [c_int], c_int)
    _bind_fn(
        "GetAccountsByBroker",
        [c_int, c_int, c_int, c_int, POINTER(TConnectorAccountIdentifierOut)],
        c_int,
    )
    _bind_fn("GetAgentNameLength", [c_int, c_int], c_int)
    _bind_fn("GetAgentName", [c_int, c_int, c_wchar_p, c_int], c_int)
    _bind_fn(
        "EnumerateAllPositionAssets",
        [POINTER(TConnectorAccountIdentifier), c_ubyte, c_long, TConnectorEnumerateAssetProc],
        c_int,
    )

    # --------------------- Utilities & Config -------------------- #
    _bind_fn("SetServerAndPort", [c_wchar_p, c_wchar_p], c_int)
    _bind_fn(
        "GetServerClock",
        [
            POINTER(c_double),
            POINTER(c_int),
            POINTER(c_int),
            POINTER(c_int),
            POINTER(c_int),
            POINTER(c_int),
            POINTER(c_int),
            POINTER(c_int),
        ],
        c_int,
    )
    _bind_fn("SetDayTrade", [c_int], c_int)
    _bind_fn("SetEnabledHistOrder", [c_int], c_int)
    _bind_fn("SetEnabledLogToDebug", [c_int], c_int)
    _bind_fn("RequestTickerInfo", [c_wchar_p, c_wchar_p], c_int)
    _bind_fn("GetHealthStatus", [POINTER(c_int)], c_int)
    _bind_fn("SetHealthCallback", [TSystemHealthCallback], c_int)
    _bind_fn("GetLastDailyClose", [c_wchar_p, c_wchar_p, POINTER(c_double), c_int], c_int)
    _bind_fn("SubscribeAdjustHistory", [c_wchar_p, c_wchar_p], c_int)
    _bind_fn("UnsubscribeAdjustHistory", [c_wchar_p, c_wchar_p], c_int)
    _bind_fn("SetAdjustHistoryCallbackV2", [TAdjustHistoryCallbackV2], c_int)
    _bind_fn("SetInvalidTickerCallback", [TInvalidTickerCallback], c_int)

    return lib


_KNOWN_DLL_FUNCTIONS: tuple[str, ...] = (
    "DLLInitializeLogin",
    "DLLInitializeMarketLogin",
    "SubscribeTicker",
    "UnsubscribeTicker",
    "SubscribePriceDepth",
    "UnsubscribePriceDepth",
    "SubscribeOfferBook",
    "UnsubscribeOfferBook",
    "SendOrder",
    "SendBuyOrder",
    "SendSellOrder",
    "SendMarketBuyOrder",
    "SendMarketSellOrder",
    "CancelOrder",
    "CancelAllOrders",
    "ChangeOrder",
    "GetAccount",
    "GetAccountCount",
    "GetPosition",
    "GetAgentName",
    "GetAgentAbbrev",
    "TranslateTrade",
    "GetOrderDetails",
    "SetAccount",
    "DLLSetAccount",
    "GetHealthStatus",
    "SetHealthCallback",
    "GetLastDailyClose",
    "SetEnabledHistOrder",
    "GetHistoryTrades",
    "SetHistoryTradeCallbackV2",
    "SubscribeAdjustHistory",
    "UnsubscribeAdjustHistory",
    "SetAdjustHistoryCallbackV2",
    "SetInvalidTickerCallback",
)


class _RealBackend:
    """:class:`Backend` implementation over the loaded native DLL.

    Instantiated by :func:`get_backend`. Do not use directly -- prefer
    injecting a ``Backend`` into :class:`~profitdll_wrapper.client.ProfitClient`.
    """

    def __init__(self, lib: ctypes.WinDLL) -> None:
        self._lib = lib
        self._fn_cache: dict[str, Any] = {
            fn_name: fn
            for fn_name in _KNOWN_DLL_FUNCTIONS
            if (fn := getattr(lib, fn_name, None)) is not None
        }

    def _call_fn(self, name: str, *args: Any, default_err: int = int(NLCode.NOT_FOUND)) -> int:
        fn = self._fn_cache.get(name)
        if fn is None:
            fn = getattr(self._lib, name, None)
            if fn is None:
                return default_err
            self._fn_cache[name] = fn
        return int(fn(*args))

    def initialize_login(
        self,
        activation_key: str,
        user: str,
        password: str,
        state_callback: object,
        daily_callback: object,
        order_change_callback: object = None,
    ) -> int:
        fn = self._call_get_fn("DLLInitializeLogin")
        if fn is None:
            return int(NLCode.NOT_FOUND)
        return int(
            fn(
                activation_key,
                user,
                password,
                state_callback,
                None,
                order_change_callback,
                None,
                None,
                daily_callback,
                None,
                None,
                None,
                None,
                None,
            )
        )

    def _call_get_fn(self, name: str) -> Any:
        fn = self._fn_cache.get(name)
        if fn is None:
            fn = getattr(self._lib, name, None)
            if fn is not None:
                self._fn_cache[name] = fn
        return fn

    def initialize_market_login(
        self,
        activation_key: str,
        user: str,
        password: str,
        state_callback: object,
        daily_callback: object,
    ) -> int:
        fn = self._call_get_fn("DLLInitializeMarketLogin")
        if fn is None:
            return int(NLCode.NOT_FOUND)
        return int(
            fn(
                activation_key,
                user,
                password,
                state_callback,
                None,
                daily_callback,
                None,
                None,
                None,
                None,
                None,
            )
        )

    def finalize(self) -> int:
        return self._call_fn("DLLFinalize", default_err=int(NLCode.OK))

    def subscribe_ticker(self, ticker: str, exchange: str) -> int:
        return self._call_fn("SubscribeTicker", ticker, exchange)

    def unsubscribe_ticker(self, ticker: str, exchange: str) -> int:
        return self._call_fn("UnsubscribeTicker", ticker, exchange)

    def set_trade_callback_v2(self, callback: object) -> int:
        cb = callback if callback is not None else TTradeCallbackV2(0)
        return self._call_fn("SetTradeCallbackV2", cb, default_err=int(NLCode.OK))

    def translate_trade(self, p_trade: int, out_trade: TConnectorTrade) -> int:
        return self._call_fn("TranslateTrade", c_size_t(p_trade), byref(out_trade))

    def get_history_trades(self, ticker: str, exchange: str, start: str, end: str) -> int:
        return self._call_fn("GetHistoryTrades", ticker, exchange, start, end)

    def set_history_trade_callback_v2(self, callback: object) -> int:
        cb = callback if callback is not None else TTradeCallbackV2(0)
        return self._call_fn("SetHistoryTradeCallbackV2", cb, default_err=int(NLCode.OK))

    # ---- Price Depth (P1) ---- #
    def subscribe_price_depth(self, asset: TConnectorAssetIdentifier) -> int:
        return self._call_fn("SubscribePriceDepth", byref(asset))

    def unsubscribe_price_depth(self, asset: TConnectorAssetIdentifier) -> int:
        return self._call_fn("UnsubscribePriceDepth", byref(asset))

    def set_price_depth_callback(self, callback: object) -> int:
        cb = callback if callback is not None else TPriceDepthCallback(0)
        return self._call_fn("SetPriceDepthCallback", cb, default_err=int(NLCode.OK))

    def subscribe_offer_book(self, ticker: str, exchange: str) -> int:
        return self._call_fn("SubscribeOfferBook", ticker, exchange)

    def unsubscribe_offer_book(self, ticker: str, exchange: str) -> int:
        return self._call_fn("UnsubscribeOfferBook", ticker, exchange)

    def set_offer_book_callback_v2(self, callback: object) -> int:
        cb = callback if callback is not None else TOfferBookCallbackV2(0)
        return self._call_fn("SetOfferBookCallbackV2", cb, default_err=int(NLCode.OK))

    def get_price_depth_side_count(self, asset: TConnectorAssetIdentifier, side: int) -> int:
        return self._call_fn("GetPriceDepthSideCount", byref(asset), c_ubyte(side))

    def get_price_group(
        self,
        asset: TConnectorAssetIdentifier,
        side: int,
        position: int,
        out_group: TConnectorPriceGroup,
    ) -> int:
        return self._call_fn(
            "GetPriceGroup", byref(asset), c_ubyte(side), position, byref(out_group)
        )

    def get_theoretical_values(
        self,
        asset: TConnectorAssetIdentifier,
        out_price: c_double,
        out_qty: c_int64,
    ) -> int:
        return self._call_fn("GetTheoreticalValues", byref(asset), byref(out_price), byref(out_qty))

    # ---- Routing & Orders (P2) ---- #
    def send_order(self, order: TConnectorSendOrder, out_id: c_int64) -> int:
        if "SendOrder" not in self._fn_cache:
            self._fn_cache["SendOrder"] = getattr(self._lib, "SendOrder", None)
        fn = self._fn_cache["SendOrder"]
        if fn is None:
            return int(NLCode.NOT_FOUND)
        res = fn(byref(order))
        out_id.value = int(res)
        return int(NLCode.OK) if int(res) > 0 else int(res)

    def send_change_order_v2(self, change: TConnectorChangeOrder) -> int:
        return self._call_fn("SendChangeOrderV2", byref(change))

    def send_cancel_order_v2(self, cancel: TConnectorCancelOrder) -> int:
        return self._call_fn("SendCancelOrderV2", byref(cancel))

    def send_cancel_orders_v2(self, cancel: TConnectorCancelOrders) -> int:
        return self._call_fn("SendCancelOrdersV2", byref(cancel))

    def send_cancel_all_orders(self, cancel: TConnectorCancelAllOrders) -> int:
        return self._call_fn("SendCancelAllOrdersV2", byref(cancel))

    def send_zero_position_v2(self, zero: TConnectorZeroPosition, out_id: c_int64) -> int:
        if "SendZeroPositionV2" not in self._fn_cache:
            self._fn_cache["SendZeroPositionV2"] = getattr(self._lib, "SendZeroPositionV2", None)
        fn = self._fn_cache["SendZeroPositionV2"]
        if fn is None:
            return int(NLCode.NOT_FOUND)
        res = fn(byref(zero))
        out_id.value = int(res)
        return int(NLCode.OK) if int(res) > 0 else int(res)

    def get_position_v2(
        self,
        out_pos: TConnectorTradingAccountPosition,
    ) -> int:
        return self._call_fn("GetPositionV2", byref(out_pos))

    def set_order_change_callback_v2(self, callback: object) -> int:
        cb = callback if callback is not None else TOrderChangeCallbackV2(0)
        return self._call_fn("SetOrderChangeCallbackV2", cb, default_err=int(NLCode.OK))

    def set_order_callback(self, callback: object) -> int:
        cb = callback if callback is not None else TConnectorOrderCallback(0)
        return self._call_fn("SetOrderCallback", cb, default_err=int(NLCode.OK))

    def set_order_history_callback(self, callback: object) -> int:
        cb = callback if callback is not None else TConnectorAccountCallback(0)
        return self._call_fn("SetOrderHistoryCallback", cb, default_err=int(NLCode.OK))

    def get_order_details(self, order_out: TConnectorOrderOut) -> int:
        return self._call_fn("GetOrderDetails", byref(order_out))

    def set_asset_position_list_callback(self, callback: object) -> int:
        cb = callback if callback is not None else TAssetPositionListCallback(0)
        return self._call_fn("SetAssetPositionListCallback", cb, default_err=int(NLCode.OK))

    def set_trading_message_result_callback(self, callback: object) -> int:
        cb = callback if callback is not None else TConnectorTradingMessageResultCallback(0)
        return self._call_fn("SetTradingMessageResultCallback", cb, default_err=int(NLCode.OK))

    def request_ticker_info(self, ticker: str, exchange: str) -> int:
        return self._call_fn("RequestTickerInfo", ticker, exchange)

    def set_asset_list_info_callback_v2(self, callback: object) -> int:
        cb = callback if callback is not None else TAssetListInfoCallbackV2(0)
        return self._call_fn("SetAssetListInfoCallbackV2", cb, default_err=int(NLCode.OK))

    def set_change_state_ticker_callback(self, callback: object) -> int:
        cb = callback if callback is not None else TChangeStateTicker(0)
        return self._call_fn("SetChangeStateTickerCallback", cb, default_err=int(NLCode.OK))

    # ---- Accounts & Enumeration ---- #
    def get_account_count(self) -> int:
        return self._call_fn("GetAccountCount", default_err=0)

    def get_accounts(
        self, start_source: int, start_dest: int, count: int, accounts_out: Any
    ) -> int:
        return self._call_fn("GetAccounts", start_source, start_dest, count, accounts_out)

    def get_account_details(self, account_out: TConnectorTradingAccountOut) -> int:
        return self._call_fn("GetAccountDetails", byref(account_out))

    def get_sub_account_count(self, master_id: TConnectorAccountIdentifier) -> int:
        return self._call_fn("GetSubAccountCount", byref(master_id), default_err=0)

    def get_sub_accounts(
        self,
        master_id: TConnectorAccountIdentifier,
        start_source: int,
        start_dest: int,
        count: int,
        accounts_out: Any,
    ) -> int:
        return self._call_fn(
            "GetSubAccounts", byref(master_id), start_source, start_dest, count, accounts_out
        )

    def get_account_count_by_broker(self, broker_id: int) -> int:
        return self._call_fn("GetAccountCountByBroker", broker_id, default_err=0)

    def get_accounts_by_broker(
        self, broker_id: int, start_source: int, start_dest: int, count: int, accounts_out: Any
    ) -> int:
        return self._call_fn(
            "GetAccountsByBroker", broker_id, start_source, start_dest, count, accounts_out
        )

    def has_orders_in_interval(
        self, account_id: TConnectorAccountIdentifier, start: Any, end: Any
    ) -> int:
        return self._call_fn("HasOrdersInInterval", byref(account_id), start, end)

    def enumerate_orders_by_interval(
        self,
        account_id: TConnectorAccountIdentifier,
        order_version: int,
        start: Any,
        end: Any,
        param: int,
        callback: object,
    ) -> int:
        return self._call_fn(
            "EnumerateOrdersByInterval",
            byref(account_id),
            c_ubyte(order_version),
            start,
            end,
            param,
            callback,
        )

    def enumerate_all_orders(
        self,
        account_id: TConnectorAccountIdentifier,
        order_version: int,
        param: int,
        callback: object,
    ) -> int:
        return self._call_fn(
            "EnumerateAllOrders", byref(account_id), c_ubyte(order_version), param, callback
        )

    def enumerate_all_position_assets(
        self,
        account_id: TConnectorAccountIdentifier,
        asset_version: int,
        param: int,
        callback: object,
    ) -> int:
        return self._call_fn(
            "EnumerateAllPositionAssets", byref(account_id), c_ubyte(asset_version), param, callback
        )

    def get_agent_name_length(self, agent_id: int, short_flag: int) -> int:
        return self._call_fn("GetAgentNameLength", agent_id, short_flag, default_err=0)

    def get_agent_name(self, count: int, agent_id: int, pwc_agent: Any, short_flag: int) -> int:
        return self._call_fn("GetAgentName", count, agent_id, pwc_agent, short_flag)

    def set_day_trade(self, use_day_trade: int) -> int:
        return self._call_fn("SetDayTrade", use_day_trade)

    def set_enabled_log_to_debug(self, enabled: int) -> int:
        return self._call_fn("SetEnabledLogToDebug", enabled)

    def get_server_clock(
        self,
        dt_date: c_double,
        year: c_int,
        month: c_int,
        day: c_int,
        hour: c_int,
        minute: c_int,
        sec: c_int,
        millisec: c_int,
    ) -> int:
        return self._call_fn(
            "GetServerClock",
            byref(dt_date),
            byref(year),
            byref(month),
            byref(day),
            byref(hour),
            byref(minute),
            byref(sec),
            byref(millisec),
        )

    def get_health_status(self, out_state: Any) -> int:
        return self._call_fn("GetHealthStatus", out_state)

    def set_health_callback(self, callback: object) -> int:
        cb = callback if callback is not None else TSystemHealthCallback(0)
        return self._call_fn("SetHealthCallback", cb)

    def get_last_daily_close(
        self, ticker: str, exchange: str, out_close: Any, adjusted: int
    ) -> int:
        return self._call_fn("GetLastDailyClose", ticker, exchange, out_close, adjusted)

    def set_enabled_hist_order(self, enabled: int) -> int:
        return self._call_fn("SetEnabledHistOrder", enabled)

    def subscribe_adjust_history(self, ticker: str, exchange: str) -> int:
        return self._call_fn("SubscribeAdjustHistory", ticker, exchange)

    def unsubscribe_adjust_history(self, ticker: str, exchange: str) -> int:
        return self._call_fn("UnsubscribeAdjustHistory", ticker, exchange)

    def set_adjust_history_callback_v2(self, callback: object) -> int:
        cb = callback if callback is not None else TAdjustHistoryCallbackV2(0)
        return self._call_fn("SetAdjustHistoryCallbackV2", cb)

    def set_invalid_ticker_callback(self, callback: object) -> int:
        cb = callback if callback is not None else TInvalidTickerCallback(0)
        return self._call_fn("SetInvalidTickerCallback", cb)


def get_backend() -> Backend:
    """Loads native DLL, binds signatures, and returns real Backend instance.

    Should be called on Windows OS with valid ProfitDLL installation.
    """
    from profitdll_wrapper._bindings.loader import _load_dll

    lib = bind(_load_dll())
    backend = _RealBackend(lib)
    _register_active_backend(backend)
    return backend


# Tracks live backends so the process can DLLFinalize them on interpreter
# shutdown. Without this, a ProfitDLL that was DLLInitializeLogin'd but never
# explicitly disconnected leaves its native ConnectorThread running; when the
# interpreter tears down and the OS unloads the DLL, that thread triggers a
# "Windows fatal exception: access violation".
_active_backends: list[_RealBackend] = []


def _register_active_backend(backend: _RealBackend) -> None:
    """Remembers a backend so it can be finalized at interpreter shutdown."""
    if backend not in _active_backends:
        _active_backends.append(backend)


def _unregister_active_backend(backend: object) -> None:
    """Drops a backend from the atexit safety net after explicit disconnect."""
    with contextlib.suppress(ValueError):
        _active_backends.remove(backend)  # type: ignore[arg-type]


def finalize_active_backends() -> None:
    """Finalizes every still-initialized backend. Safe to call multiple times."""
    global _interpreter_shutting_down
    _interpreter_shutting_down = True
    for backend in _active_backends:
        with contextlib.suppress(Exception):
            backend.finalize()
    _active_backends.clear()


# Set when the atexit safety net finalizes backends; lets client state
# callbacks ignore the DISCONNECTED notifications emitted by DLLFinalize
# itself during interpreter shutdown.
_interpreter_shutting_down = False


atexit.register(finalize_active_backends)


__all__ = ["Backend", "bind", "get_backend"]
