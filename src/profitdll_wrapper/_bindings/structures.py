"""ctypes structures matching ProfitDLL C/Delphi ABI layouts.

Fields use PascalCase to match DLL memory layout.
Python high-level dataclass conversions occur in profitdll_wrapper._types.
"""

from __future__ import annotations

import ctypes
from ctypes import (
    POINTER,
    Structure,
    c_double,
    c_int,
    c_int64,
    c_longlong,
    c_ubyte,
    c_uint,
    c_ushort,
    c_void_p,
    c_wchar,
    c_wchar_p,
)


class SystemTime(Structure):
    """TSystemTime — mirrors Win32 SYSTEMTIME (8 x WORD)."""

    _fields_ = [
        ("wYear", c_ushort),
        ("wMonth", c_ushort),
        ("wDayOfWeek", c_ushort),
        ("wDay", c_ushort),
        ("wHour", c_ushort),
        ("wMinute", c_ushort),
        ("wSecond", c_ushort),
        ("wMilliseconds", c_ushort),
    ]


class TConnectorTrade(Structure):
    """TConnectorTrade — trade data filled by TranslateTrade."""

    _fields_ = [
        ("Version", c_ubyte),
        ("TradeDate", SystemTime),
        ("TradeNumber", c_uint),
        ("Price", c_double),
        ("Quantity", c_longlong),
        ("Volume", c_double),
        ("BuyAgent", c_int),
        ("SellAgent", c_int),
        ("TradeType", c_ubyte),
    ]


class TConnectorAssetIdentifier(Structure):
    """TConnectorAssetIdentifier — asset identifier in V2 callbacks."""

    _fields_ = [
        ("Version", c_ubyte),
        ("Ticker", c_wchar_p),
        ("Exchange", c_wchar_p),
        ("FeedType", c_ubyte),
    ]


class TConnectorAssetIdentifierSafe(Structure):
    """TConnectorAssetIdentifierSafe — safe asset identifier using void pointers."""

    _fields_ = [
        ("Version", c_ubyte),
        ("Ticker", c_void_p),
        ("Exchange", c_void_p),
        ("FeedType", c_ubyte),
    ]


class TAssetIDRec(Structure):
    """TAssetIDRec — packed asset ID record."""

    _pack_ = 1
    _fields_ = [
        ("pwcTicker", c_wchar_p),
        ("pwcBolsa", c_wchar_p),
        ("nFeed", c_int),
    ]


PConnectorTrade = POINTER(TConnectorTrade)


class TConnectorPriceGroup(Structure):
    """TConnectorPriceGroup — price book level filled by GetPriceGroup."""

    _fields_ = [
        ("Version", c_ubyte),
        ("Price", c_double),
        ("Count", c_int64),
        ("Quantity", c_int64),
        ("PriceGroupFlags", c_uint),
    ]


PG_IS_THEORIC: int = 1


class TAssetID(Structure):
    """TAssetID — legacy asset identifier structure."""

    _fields_ = [
        ("ticker", c_wchar_p),
        ("bolsa", c_wchar_p),
        ("feed", c_int),
    ]


class TConnectorAccountIdentifier(Structure):
    """TConnectorAccountIdentifier — trading account identifier."""

    _fields_ = [
        ("Version", c_ubyte),
        ("BrokerID", c_int),
        ("AccountID", c_wchar_p),
        ("SubAccountID", c_wchar_p),
        ("Reserved", c_int64),
    ]


class TConnectorOrderIdentifier(Structure):
    """TConnectorOrderIdentifier — order identifier structure."""

    _fields_ = [
        ("Version", c_ubyte),
        ("LocalOrderID", c_int64),
        ("ClOrderID", c_wchar_p),
    ]


class TConnectorAssetIdentifierOut(Structure):
    """TConnectorAssetIdentifierOut — output version of asset ID with length fields."""

    _fields_ = [
        ("Version", c_ubyte),
        ("Ticker", c_wchar_p),
        ("TickerLength", c_int),
        ("Exchange", c_wchar_p),
        ("ExchangeLength", c_int),
        ("FeedType", c_ubyte),
    ]


class TConnectorAccountIdentifierOut(Structure):
    """TConnectorAccountIdentifierOut — output version of account ID with inline buffers."""

    _fields_ = [
        ("Version", c_ubyte),
        ("BrokerID", c_int),
        ("AccountID", c_wchar * 100),
        ("AccountIDLength", c_int),
        ("SubAccountID", c_wchar * 100),
        ("SubAccountIDLength", c_int),
        ("Reserved", c_int64),
    ]


class TConnectorOrderOut(Structure):
    """TConnectorOrderOut — detailed order information structure."""

    _fields_ = [
        ("Version", c_ubyte),
        ("OrderID", TConnectorOrderIdentifier),
        ("AccountID", TConnectorAccountIdentifierOut),
        ("AssetID", TConnectorAssetIdentifierOut),
        ("Quantity", c_longlong),
        ("TradedQuantity", c_longlong),
        ("LeavesQuantity", c_longlong),
        ("Price", c_double),
        ("StopPrice", c_double),
        ("AveragePrice", c_double),
        ("OrderSide", c_ubyte),
        ("OrderType", c_ubyte),
        ("OrderStatus", c_ubyte),
        ("ValidityType", c_ubyte),
        ("Date", SystemTime),
        ("LastUpdate", SystemTime),
        ("CloseDate", SystemTime),
        ("ValidityDate", SystemTime),
        ("TextMessage", c_wchar_p),
        ("TextMessageLength", c_int),
        ("EventID", c_int64),
    ]


class TConnectorSendOrder(Structure):
    """TConnectorSendOrder — input parameters for order placement via SendOrder."""

    _fields_ = [
        ("Version", c_ubyte),
        ("AccountID", TConnectorAccountIdentifier),
        ("AssetID", TConnectorAssetIdentifier),
        ("Password", c_wchar_p),
        ("OrderType", c_ubyte),
        ("OrderSide", c_ubyte),
        ("Price", c_double),
        ("StopPrice", c_double),
        ("Quantity", c_longlong),
        ("MessageID", c_longlong),
    ]


class TConnectorCancelOrder(Structure):
    """TConnectorCancelOrder — input parameters for SendCancelOrderV2."""

    _fields_ = [
        ("Version", c_ubyte),
        ("AccountID", TConnectorAccountIdentifier),
        ("OrderID", TConnectorOrderIdentifier),
        ("Password", c_wchar_p),
        ("MessageID", c_longlong),
    ]


class TConnectorCancelOrders(Structure):
    """TConnectorCancelOrders — input parameters for SendCancelOrdersV2."""

    _fields_ = [
        ("Version", c_ubyte),
        ("AccountID", TConnectorAccountIdentifier),
        ("AssetID", TConnectorAssetIdentifier),
        ("Password", c_wchar_p),
    ]


class TConnectorCancelAllOrders(Structure):
    """TConnectorCancelAllOrders — input parameters for SendCancelAllOrdersV2."""

    _fields_ = [
        ("Version", c_ubyte),
        ("AccountID", TConnectorAccountIdentifier),
        ("Password", c_wchar_p),
    ]


class TConnectorZeroPosition(Structure):
    """TConnectorZeroPosition — input parameters for SendZeroPositionV2."""

    _fields_ = [
        ("Version", c_ubyte),
        ("AccountID", TConnectorAccountIdentifier),
        ("AssetID", TConnectorAssetIdentifier),
        ("Password", c_wchar_p),
        ("Price", c_double),
        ("PositionType", c_ubyte),
        ("MessageID", c_int64),
    ]


class TConnectorChangeOrder(Structure):
    """TConnectorChangeOrder — input parameters for SendChangeOrderV2."""

    _fields_ = [
        ("Version", c_ubyte),
        ("AccountID", TConnectorAccountIdentifier),
        ("OrderID", TConnectorOrderIdentifier),
        ("Password", c_wchar_p),
        ("Price", c_double),
        ("StopPrice", c_double),
        ("Quantity", c_int64),
        ("MessageID", c_int64),
    ]


class TConnectorTradingAccountOut(Structure):
    """TConnectorTradingAccountOut — trading account detail structure."""

    _fields_ = [
        ("Version", c_ubyte),
        ("AccountID", TConnectorAccountIdentifier),
        ("BrokerName", c_wchar_p),
        ("BrokerNameLength", c_int),
        ("OwnerName", c_wchar_p),
        ("OwnerNameLength", c_int),
        ("SubOwnerName", c_wchar_p),
        ("SubOwnerNameLength", c_int),
        ("AccountFlags", c_int),
        ("AccountType", c_ubyte),
    ]


class TConnectorOrder(Structure):
    """TConnectorOrder — order structure used in order enumeration callbacks."""

    _fields_ = [
        ("Version", c_ubyte),
        ("OrderID", TConnectorOrderIdentifier),
        ("AccountID", TConnectorAccountIdentifier),
        ("AssetID", TConnectorAssetIdentifier),
        ("Quantity", c_int64),
        ("TradedQuantity", c_int64),
        ("LeavesQuantity", c_int64),
        ("Price", c_double),
        ("StopPrice", c_double),
        ("AveragePrice", c_double),
        ("OrderSide", c_ubyte),
        ("OrderType", c_ubyte),
        ("OrderStatus", c_ubyte),
        ("ValidityType", c_ubyte),
        ("Date", SystemTime),
        ("LastUpdate", SystemTime),
        ("CloseDate", SystemTime),
        ("ValidityDate", SystemTime),
        ("TextMessage", c_wchar_p),
        ("EventID", c_int64),
    ]


class TConnectorTradingMessageResult(Structure):
    """TConnectorTradingMessageResult — trading result message from DLL."""

    _fields_ = [
        ("Version", c_ubyte),
        ("BrokerID", c_int),
        ("OrderID", TConnectorOrderIdentifier),
        ("MessageID", c_int64),
        ("ResultCode", c_ubyte),
        ("Message", c_wchar_p),
        ("MessageLength", c_int),
    ]


class TConnectorTradingAccountPosition(Structure):
    """TConnectorTradingAccountPosition — position structure returned by GetPositionV2."""

    _fields_ = [
        ("Version", c_ubyte),
        ("AccountID", TConnectorAccountIdentifier),
        ("AssetID", TConnectorAssetIdentifier),
        ("OpenQuantity", c_longlong),
        ("OpenAveragePrice", c_double),
        ("OpenSide", c_ubyte),
        ("DailyAverageSellPrice", c_double),
        ("DailySellQuantity", c_longlong),
        ("DailyAverageBuyPrice", c_double),
        ("DailyBuyQuantity", c_longlong),
        ("DailyQuantityD1", c_longlong),
        ("DailyQuantityD2", c_longlong),
        ("DailyQuantityD3", c_longlong),
        ("DailyQuantityBlocked", c_longlong),
        ("DailyQuantityPending", c_longlong),
        ("DailyQuantityAlloc", c_longlong),
        ("DailyQuantityProvision", c_longlong),
        ("DailyQuantity", c_longlong),
        ("DailyQuantityAvailable", c_longlong),
        ("PositionType", c_ubyte),
        ("EventID", c_int64),
    ]


__all__ = [
    "PG_IS_THEORIC",
    "PConnectorTrade",
    "SystemTime",
    "TAssetID",
    "TAssetIDRec",
    "TConnectorAccountIdentifier",
    "TConnectorAccountIdentifierOut",
    "TConnectorAssetIdentifier",
    "TConnectorAssetIdentifierOut",
    "TConnectorAssetIdentifierSafe",
    "TConnectorCancelAllOrders",
    "TConnectorCancelOrder",
    "TConnectorCancelOrders",
    "TConnectorChangeOrder",
    "TConnectorOrder",
    "TConnectorOrderIdentifier",
    "TConnectorOrderOut",
    "TConnectorPriceGroup",
    "TConnectorSendOrder",
    "TConnectorTrade",
    "TConnectorTradingAccountOut",
    "TConnectorTradingAccountPosition",
    "TConnectorTradingMessageResult",
    "TConnectorZeroPosition",
    "ctypes",
]
