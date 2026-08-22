"""Testes para _RealBackend e get_backend() usando ctypes.WinDLL mockado."""

from __future__ import annotations

from unittest.mock import MagicMock

from profitdll_wrapper._bindings.callbacks import TDailyCallback, TStateCallback
from profitdll_wrapper._bindings.functions import _RealBackend, get_backend
from profitdll_wrapper._bindings.structures import (
    TConnectorAssetIdentifier,
    TConnectorPriceGroup,
    TConnectorTrade,
)


class TestRealBackendWrapper:
    """Verifica se _RealBackend repassa os parâmetros para ctypes WinDLL adequadamente."""

    def test_initialize_login(self) -> None:
        mock_lib = MagicMock()
        mock_lib.DLLInitializeLogin.return_value = 0
        backend = _RealBackend(mock_lib)

        state_cb = TStateCallback(lambda s, r: None)
        daily_cb = TDailyCallback(lambda *args: None)

        res = backend.initialize_login("key", "user", "pass", state_cb, daily_cb)
        assert res == 0
        mock_lib.DLLInitializeLogin.assert_called_once_with(
            "key",
            "user",
            "pass",
            state_cb,
            None,
            None,
            None,
            None,
            daily_cb,
            None,
            None,
            None,
            None,
            None,
        )

    def test_initialize_market_login(self) -> None:
        mock_lib = MagicMock()
        mock_lib.DLLInitializeMarketLogin.return_value = 0
        backend = _RealBackend(mock_lib)

        state_cb = TStateCallback(lambda s, r: None)
        daily_cb = TDailyCallback(lambda *args: None)

        res = backend.initialize_market_login("key", "user", "pass", state_cb, daily_cb)
        assert res == 0
        mock_lib.DLLInitializeMarketLogin.assert_called_once_with(
            "key", "user", "pass", state_cb, None, daily_cb, None, None, None, None, None
        )

    def test_finalize(self) -> None:
        mock_lib = MagicMock()
        mock_lib.DLLFinalize.return_value = 0
        backend = _RealBackend(mock_lib)
        assert backend.finalize() == 0
        mock_lib.DLLFinalize.assert_called_once()

    def test_subscribe_and_unsubscribe_ticker(self) -> None:
        mock_lib = MagicMock()
        mock_lib.SubscribeTicker.return_value = 0
        mock_lib.UnsubscribeTicker.return_value = 0
        backend = _RealBackend(mock_lib)

        assert backend.subscribe_ticker("DOLU26", "F") == 0
        mock_lib.SubscribeTicker.assert_called_once_with("DOLU26", "F")

        assert backend.unsubscribe_ticker("DOLU26", "F") == 0
        mock_lib.UnsubscribeTicker.assert_called_once_with("DOLU26", "F")

    def test_set_trade_callback_v2(self) -> None:
        mock_lib = MagicMock()
        mock_lib.SetTradeCallbackV2.return_value = 0
        backend = _RealBackend(mock_lib)

        dummy_cb = object()
        assert backend.set_trade_callback_v2(dummy_cb) == 0
        mock_lib.SetTradeCallbackV2.assert_called_once_with(dummy_cb)

    def test_translate_trade(self) -> None:
        mock_lib = MagicMock()
        mock_lib.TranslateTrade.return_value = 0
        backend = _RealBackend(mock_lib)

        trade = TConnectorTrade()
        assert backend.translate_trade(12345, trade) == 0
        mock_lib.TranslateTrade.assert_called_once()

    def test_price_depth_methods(self) -> None:
        mock_lib = MagicMock()
        mock_lib.SubscribePriceDepth.return_value = 0
        mock_lib.UnsubscribePriceDepth.return_value = 0
        mock_lib.SetPriceDepthCallback.return_value = 0
        mock_lib.GetPriceDepthSideCount.return_value = 10
        mock_lib.GetPriceGroup.return_value = 0
        mock_lib.GetTheoreticalValues.return_value = 0

        backend = _RealBackend(mock_lib)
        asset = TConnectorAssetIdentifier(Version=0, Ticker="DOLU26", Exchange="F", FeedType=0)

        assert backend.subscribe_price_depth(asset) == 0
        mock_lib.SubscribePriceDepth.assert_called_once()

        assert backend.unsubscribe_price_depth(asset) == 0
        mock_lib.UnsubscribePriceDepth.assert_called_once()

        dummy_cb = object()
        assert backend.set_price_depth_callback(dummy_cb) == 0
        mock_lib.SetPriceDepthCallback.assert_called_once_with(dummy_cb)

        assert backend.get_price_depth_side_count(asset, 0) == 10
        mock_lib.GetPriceDepthSideCount.assert_called_once()

        group = TConnectorPriceGroup()
        assert backend.get_price_group(asset, 0, 1, group) == 0
        mock_lib.GetPriceGroup.assert_called_once()

        from ctypes import c_double, c_int64

        price = c_double()
        qty = c_int64()
        assert backend.get_theoretical_values(asset, price, qty) == 0
        mock_lib.GetTheoreticalValues.assert_called_once()


class TestGetBackend:
    def test_get_backend_instantiates_real_backend(self, monkeypatch: object) -> None:
        import pytest

        assert isinstance(monkeypatch, pytest.MonkeyPatch)
        mock_lib = MagicMock()
        monkeypatch.setattr("profitdll_wrapper._bindings.loader._load_dll", lambda: mock_lib)
        backend = get_backend()
        assert isinstance(backend, _RealBackend)
