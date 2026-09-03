"""Testes de contrato ABI (sem carregar a DLL física).

Valida se a declaração de bindings em Python (argtypes, restype, layout de structs,
packing e assinaturas WINFUNCTYPE) bate estritamente com a especificação oficial
da ProfitDLL (materiais de referência da Nelogica, não distribuídos neste repo).
"""

from __future__ import annotations

from ctypes import (
    POINTER,
    c_double,
    c_int,
    c_int32,
    c_int64,
    c_longlong,
    c_size_t,
    c_ubyte,
    c_uint,
    c_ushort,
    c_void_p,
    c_wchar_p,
    sizeof,
)
from unittest.mock import MagicMock

from profitdll_wrapper._bindings.callbacks import (
    TDailyCallback,
    TPriceDepthCallback,
    TProgressCallback,
    TStateCallback,
    TTradeCallbackV2,
)
from profitdll_wrapper._bindings.functions import bind
from profitdll_wrapper._bindings.structures import (
    SystemTime,
    TAssetID,
    TAssetIDRec,
    TConnectorAssetIdentifier,
    TConnectorAssetIdentifierSafe,
    TConnectorCancelOrder,
    TConnectorCancelOrders,
    TConnectorPriceGroup,
    TConnectorSendOrder,
    TConnectorTrade,
)


class TestABIStructureLayouts:
    """Verifica layouts de structs contra a especificação oficial da DLL."""

    def test_system_time_fields_and_types(self) -> None:
        expected = [
            ("wYear", c_ushort),
            ("wMonth", c_ushort),
            ("wDayOfWeek", c_ushort),
            ("wDay", c_ushort),
            ("wHour", c_ushort),
            ("wMinute", c_ushort),
            ("wSecond", c_ushort),
            ("wMilliseconds", c_ushort),
        ]
        actual = [(f[0], f[1]) for f in SystemTime._fields_]
        assert actual == expected

    def test_tconnector_trade_fields_and_types(self) -> None:
        expected = [
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
        actual = [(f[0], f[1]) for f in TConnectorTrade._fields_]
        assert actual == expected

    def test_tconnector_asset_identifier_fields_and_types(self) -> None:
        expected = [
            ("Version", c_ubyte),
            ("Ticker", c_wchar_p),
            ("Exchange", c_wchar_p),
            ("FeedType", c_ubyte),
        ]
        actual = [(f[0], f[1]) for f in TConnectorAssetIdentifier._fields_]
        assert actual == expected

    def test_tconnector_asset_identifier_safe_fields_and_types(self) -> None:
        expected = [
            ("Version", c_ubyte),
            ("Ticker", c_void_p),
            ("Exchange", c_void_p),
            ("FeedType", c_ubyte),
        ]
        actual = [(f[0], f[1]) for f in TConnectorAssetIdentifierSafe._fields_]
        assert actual == expected

    def test_tasset_id_rec_packed(self) -> None:
        assert getattr(TAssetIDRec, "_pack_", None) == 1
        expected = [
            ("pwcTicker", c_wchar_p),
            ("pwcBolsa", c_wchar_p),
            ("nFeed", c_int),
        ]
        actual = [(f[0], f[1]) for f in TAssetIDRec._fields_]
        assert actual == expected

    def test_tconnector_price_group_fields_and_types(self) -> None:
        expected = [
            ("Version", c_ubyte),
            ("Price", c_double),
            ("Count", c_int64),
            ("Quantity", c_int64),
            ("PriceGroupFlags", c_uint),
        ]
        actual = [(f[0], f[1]) for f in TConnectorPriceGroup._fields_]
        assert actual == expected

    def test_tconnector_price_group_size(self) -> None:
        # Layout Delphi x64: Count/Quantity são Int64 (8 bytes cada); com o
        # alinhamento padrão a struct ocupa 40 bytes. Regredir esses campos
        # para 32 bits leria o padding entre campos como dados (bug que zereava
        # count/quantity nos eventos de price depth).
        assert sizeof(TConnectorPriceGroup) == 40

    def test_tasset_id_legacy_fields_and_types(self) -> None:
        expected = [
            ("ticker", c_wchar_p),
            ("bolsa", c_wchar_p),
            ("feed", c_int),
        ]
        actual = [(f[0], f[1]) for f in TAssetID._fields_]
        assert actual == expected


class TestABICallbackSignatures:
    """Verifica assinaturas de callbacks ctypes contra a especificação oficial da DLL."""

    def test_state_callback_argtypes(self) -> None:
        assert list(TStateCallback._argtypes_) == [c_int32, c_int32]
        assert TStateCallback._restype_ is None

    def test_trade_callback_v2_argtypes(self) -> None:
        assert list(TTradeCallbackV2._argtypes_) == [TConnectorAssetIdentifier, c_size_t, c_uint]
        assert TTradeCallbackV2._restype_ is None

    def test_price_depth_callback_argtypes(self) -> None:
        assert list(TPriceDepthCallback._argtypes_) == [
            TConnectorAssetIdentifier,
            c_ubyte,
            c_int32,
            c_ubyte,
        ]
        assert TPriceDepthCallback._restype_ is None

    def test_daily_callback_argtypes(self) -> None:
        expected = [
            TAssetID,
            c_wchar_p,
            c_double,
            c_double,
            c_double,
            c_double,
            c_double,
            c_double,
            c_double,
            c_double,
            c_double,
            c_double,
            c_int32,
            c_int32,
            c_int32,
            c_int32,
            c_int32,
            c_int32,
            c_int32,
        ]
        assert list(TDailyCallback._argtypes_) == expected
        assert TDailyCallback._restype_ is None

    def test_progress_callback_argtypes(self) -> None:
        # Manual (§3.2): TProgressCallback = procedure(rAssetID: TAssetIDRec;
        # nProgress: Integer) stdcall.
        assert list(TProgressCallback._argtypes_) == [TAssetID, c_int32]
        assert TProgressCallback._restype_ is None


class TestABIFunctionBindings:
    """Verifica se bind(mock_lib) configura argtypes/restype conforme vendor."""

    def test_bind_configures_all_functions(self) -> None:
        mock_lib = MagicMock()

        bind(mock_lib)

        # DLLInitializeMarketLogin
        assert mock_lib.DLLInitializeMarketLogin.argtypes == [
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
            TStateCallback,
            c_wchar_p,
            TDailyCallback,
            c_wchar_p,
            c_wchar_p,
            c_wchar_p,
            TProgressCallback,
            c_wchar_p,
        ]
        assert mock_lib.DLLInitializeMarketLogin.restype == c_int

        # DLLInitializeLogin
        assert mock_lib.DLLInitializeLogin.argtypes == [
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
            TProgressCallback,
            c_wchar_p,
        ]
        assert mock_lib.DLLInitializeLogin.restype == c_int

        # DLLFinalize
        assert mock_lib.DLLFinalize.argtypes == []
        assert mock_lib.DLLFinalize.restype == c_int

        # SetSerieProgressCallback
        assert mock_lib.SetSerieProgressCallback.argtypes == [TProgressCallback]
        assert mock_lib.SetSerieProgressCallback.restype == c_int

        # SubscribeTicker / UnsubscribeTicker
        assert mock_lib.SubscribeTicker.argtypes == [c_wchar_p, c_wchar_p]
        assert mock_lib.SubscribeTicker.restype == c_int
        assert mock_lib.UnsubscribeTicker.argtypes == [c_wchar_p, c_wchar_p]
        assert mock_lib.UnsubscribeTicker.restype == c_int

        # SetTradeCallbackV2
        assert mock_lib.SetTradeCallbackV2.argtypes == [TTradeCallbackV2]
        assert mock_lib.SetTradeCallbackV2.restype == c_int

        # TranslateTrade
        assert mock_lib.TranslateTrade.argtypes == [c_size_t, POINTER(TConnectorTrade)]
        assert mock_lib.TranslateTrade.restype == c_int

        # SubscribePriceDepth / UnsubscribePriceDepth
        assert mock_lib.SubscribePriceDepth.argtypes == [POINTER(TConnectorAssetIdentifier)]
        assert mock_lib.SubscribePriceDepth.restype == c_int
        assert mock_lib.UnsubscribePriceDepth.argtypes == [POINTER(TConnectorAssetIdentifier)]
        assert mock_lib.UnsubscribePriceDepth.restype == c_int

        # SetPriceDepthCallback
        assert mock_lib.SetPriceDepthCallback.argtypes == [TPriceDepthCallback]
        assert mock_lib.SetPriceDepthCallback.restype == c_int

        # GetPriceDepthSideCount
        assert mock_lib.GetPriceDepthSideCount.argtypes == [
            POINTER(TConnectorAssetIdentifier),
            c_ubyte,
        ]
        assert mock_lib.GetPriceDepthSideCount.restype == c_int

        # GetPriceGroup
        assert mock_lib.GetPriceGroup.argtypes == [
            POINTER(TConnectorAssetIdentifier),
            c_ubyte,
            c_int,
            POINTER(TConnectorPriceGroup),
        ]
        assert mock_lib.GetPriceGroup.restype == c_int

        # GetTheoreticalValues
        assert mock_lib.GetTheoreticalValues.argtypes == [
            POINTER(TConnectorAssetIdentifier),
            POINTER(c_double),
            POINTER(c_int64),
        ]
        assert mock_lib.GetTheoreticalValues.restype == c_int

        # SendOrder
        assert mock_lib.SendOrder.argtypes == [POINTER(TConnectorSendOrder)]
        assert mock_lib.SendOrder.restype == c_int64

        # SendCancelOrderV2
        assert mock_lib.SendCancelOrderV2.argtypes == [POINTER(TConnectorCancelOrder)]
        assert mock_lib.SendCancelOrderV2.restype == c_int

        # SendCancelOrdersV2
        assert mock_lib.SendCancelOrdersV2.argtypes == [POINTER(TConnectorCancelOrders)]
        assert mock_lib.SendCancelOrdersV2.restype == c_int
