"""Testes dos dataclasses públicos (Trade, AssetId, PriceLevel, DailyCandle)."""

from __future__ import annotations

import datetime

import pytest

from profitdll_wrapper._bindings.enums import BookSide, BookUpdateType
from profitdll_wrapper._types.models import (
    AssetId,
    DailyCandle,
    PriceBookSnapshot,
    PriceLevel,
    Trade,
)


class TestAssetId:
    def test_construction(self) -> None:
        a = AssetId(ticker="WDOFUT", exchange="B")
        assert a.ticker == "WDOFUT"
        assert a.exchange == "B"

    def test_immutable(self) -> None:
        a = AssetId(ticker="WDOFUT", exchange="B")
        with pytest.raises(AttributeError):  # dataclasses.FrozenInstanceError
            a.ticker = "PETR4"  # type: ignore[misc]


class TestTrade:
    def _make_trade(self) -> Trade:
        return Trade(
            asset=AssetId(ticker="WDOFUT", exchange="F"),
            trade_number=123,
            price=5120.5,
            quantity=10,
            volume=51205.0,
            buy_agent=101,
            sell_agent=202,
            trade_type=2,
            timestamp=datetime.datetime(2026, 7, 31, 10, 0, 0),
            is_edit=False,
        )

    def test_construction(self) -> None:
        t = self._make_trade()
        assert t.trade_number == 123
        assert t.price == 5120.5
        assert t.asset.ticker == "WDOFUT"
        assert t.timestamp == datetime.datetime(2026, 7, 31, 10, 0, 0)
        assert t.date == t.timestamp

    def test_immutable(self) -> None:
        t = self._make_trade()
        with pytest.raises(AttributeError):  # dataclasses.FrozenInstanceError
            t.price = 999.0  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        t1 = self._make_trade()
        t2 = self._make_trade()
        assert t1 == t2


class TestPriceLevel:
    def _make_level(self, **overrides: object) -> PriceLevel:
        defaults: dict[str, object] = {
            "asset": AssetId(ticker="PETR4", exchange="B"),
            "side": BookSide.BUY,
            "update_type": BookUpdateType.EDIT,
            "position": 0,
            "price": 28.50,
            "count": 3,
            "quantity": 1000,
            "is_theoretical": False,
        }
        defaults.update(overrides)
        return PriceLevel(**defaults)  # type: ignore[arg-type]

    def test_construction(self) -> None:
        lvl = self._make_level()
        assert lvl.price == 28.50
        assert lvl.side is BookSide.BUY
        assert lvl.asset.ticker == "PETR4"

    def test_default_is_not_theoretical(self) -> None:
        assert self._make_level().is_theoretical is False

    def test_immutable(self) -> None:
        lvl = self._make_level()
        with pytest.raises(AttributeError):
            lvl.price = 1.0  # type: ignore[misc]


class TestPriceBookSnapshot:
    def test_default_empty_tuples(self) -> None:
        snap = PriceBookSnapshot(asset=AssetId(ticker="PETR4", exchange="B"))
        assert snap.buy_levels == ()
        assert snap.sell_levels == ()

    def test_immutable(self) -> None:
        snap = PriceBookSnapshot(asset=AssetId(ticker="PETR4", exchange="B"))
        with pytest.raises(AttributeError):
            snap.asset = AssetId(ticker="X", exchange="B")  # type: ignore[misc]


class TestDailyCandle:
    def _make_daily(self) -> DailyCandle:
        return DailyCandle(
            asset=AssetId(ticker="WDOFUT", exchange="F"),
            date="31/07/2026 18:00:00.000",
            open=5120.0,
            high=5150.0,
            low=5100.0,
            close=5130.5,
            volume=1000000.0,
            adjustment=5100.0,
            max_limit=5400.0,
            min_limit=4900.0,
            volume_buyer=600000.0,
            volume_seller=400000.0,
            quantity=200,
            trades=50,
            open_interest=10000,
            quantity_buyer=120,
            quantity_seller=80,
            trades_buyer=30,
            trades_seller=20,
        )

    def test_construction(self) -> None:
        d = self._make_daily()
        assert d.close == 5130.5
        assert d.open_interest == 10000
        assert d.asset.exchange == "F"

    def test_immutable(self) -> None:
        d = self._make_daily()
        with pytest.raises(AttributeError):
            d.close = 1.0  # type: ignore[misc]
