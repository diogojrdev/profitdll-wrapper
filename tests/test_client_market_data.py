"""Testes de market data do ProfitClient: subscrições, book de ofertas, trades, theoretical price."""

from __future__ import annotations

import threading
import time

import pytest

from profitdll_wrapper import (
    BookSide,
    BookUpdateType,
    DailyCandle,
    Event,
    PriceBookSnapshot,
    PriceLevel,
    ProfitAPIError,
    ProfitClient,
    Trade,
)
from profitdll_wrapper._bindings.callbacks import TC_IS_EDIT
from profitdll_wrapper._bindings.enums import ConnectionState, MarketResult, TickerState
from profitdll_wrapper._bindings.errors import NLCode
from profitdll_wrapper._bindings.structures import (
    PG_IS_THEORIC,
    TAssetID,
    TConnectorAssetIdentifier,
    TConnectorPriceGroup,
    TConnectorTrade,
)
from profitdll_wrapper._types.messages import AssetInfo, TickerStateChange
from tests.fakes.backend import FakeProfitBackend


def _client(backend: FakeProfitBackend, **kwargs: object) -> ProfitClient:
    defaults: dict[str, object] = {
        "activation_key": "key",
        "user": "user",
        "password": "pass",
        "mode": "market_data",
        "backend": backend,
    }
    defaults.update(kwargs)
    return ProfitClient(**defaults)  # type: ignore[arg-type]


class TestSubscribe:
    def test_subscribe_calls_backend(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)
        client.subscribe("WDOFUT", exchange="F")
        assert fake_backend.subscribed == [("WDOFUT", "F")]
        client.disconnect()

    def test_unsubscribe_calls_backend(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)
        client.subscribe("PETR4", exchange="B")
        client.unsubscribe("PETR4", exchange="B")
        assert ("PETR4", "B") in fake_backend.subscribed
        assert ("PETR4", "B") in fake_backend.unsubscribed
        client.disconnect()

    def test_invalid_exchange_raises_value_error(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)
        with pytest.raises(ValueError):
            client.subscribe("WDOFUT", exchange="Z")
        assert fake_backend.subscribed == []
        client.disconnect()

    def test_subscribe_propagates_dll_error(self, fake_backend: FakeProfitBackend) -> None:
        fake_backend.subscribe_result = int(NLCode.INVALID_TICKER)
        client = _client(fake_backend)
        client.connect(timeout=2.0)
        with pytest.raises(ProfitAPIError):
            client.subscribe("BOGUS", exchange="B")
        client.disconnect()


class TestTradeFlow:
    def test_trade_callback_delivered_to_user(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[Trade] = []
        ready = threading.Event()

        @client.on(Event.TRADE)
        def on_trade(trade: Trade) -> None:
            received.append(trade)
            ready.set()

        raw = TConnectorTrade()
        raw.Version = 0
        raw.TradeNumber = 999
        raw.Price = 5120.5
        raw.Quantity = 7
        raw.Volume = 5120.5 * 7
        raw.BuyAgent = 11
        raw.SellAgent = 22
        raw.TradeType = 2
        fake_backend.queue_trade(raw)

        asset = TConnectorAssetIdentifier()
        asset.Version = 0
        asset.Ticker = "WDOFUT"
        asset.Exchange = "F"
        asset.FeedType = 0

        client._dispatcher.start()
        fake_backend.trade_callback(asset, 999, 0)

        assert ready.wait(timeout=2.0)
        client.stop()

        assert len(received) == 1
        t = received[0]
        assert t.trade_number == 999
        assert t.price == 5120.5
        assert t.quantity == 7
        assert t.asset.ticker == "WDOFUT"
        assert t.asset.exchange == "F"
        assert t.is_edit is False

    def test_trade_with_edit_flag(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[Trade] = []
        ready = threading.Event()

        @client.on(Event.TRADE)
        def on_trade(trade: Trade) -> None:
            received.append(trade)
            ready.set()

        raw = TConnectorTrade()
        raw.Version = 0
        raw.TradeNumber = 1
        raw.Price = 1.0
        raw.Quantity = 1
        raw.Volume = 1.0
        fake_backend.queue_trade(raw)

        asset = TConnectorAssetIdentifier()
        asset.Version = 0
        asset.Ticker = "PETR4"
        asset.Exchange = "B"
        asset.FeedType = 0

        client._dispatcher.start()
        fake_backend.trade_callback(asset, 1, TC_IS_EDIT)

        assert ready.wait(timeout=2.0)
        client.stop()

        assert received[0].is_edit is True


class TestPriceDepthSubscribe:
    def test_subscribe_price_depth_calls_backend(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)
        client.subscribe_price_depth("PETR4", exchange="B")
        assert fake_backend.subscribed_depth == [("PETR4", "B")]
        client.disconnect()

    def test_unsubscribe_price_depth_calls_backend(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)
        client.subscribe_price_depth("PETR4", exchange="B")
        client.unsubscribe_price_depth("PETR4", exchange="B")
        assert fake_backend.unsubscribed_depth == [("PETR4", "B")]
        client.disconnect()

    def test_invalid_exchange_raises(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)
        with pytest.raises(ValueError):
            client.subscribe_price_depth("PETR4", exchange="Z")
        assert fake_backend.subscribed_depth == []
        client.disconnect()

    def test_get_price_depth_side_count_success(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        fake_backend.set_price_side_count("PETR4", 0, 10)
        fake_backend.set_price_side_count("PETR4", 1, 8)

        assert client.get_price_depth_side_count("PETR4", BookSide.BUY, exchange="B") == 10
        assert client.get_price_depth_side_count("PETR4", BookSide.SELL, exchange="B") == 8
        assert client.get_price_depth_side_count("PETR4", 0, exchange="B") == 10

    def test_get_price_depth_side_count_invalid_side(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        with pytest.raises(ValueError, match="side must be 0"):
            client.get_price_depth_side_count("PETR4", 99, exchange="B")

    def test_set_price_depth_callback_called_on_connect(
        self, fake_backend: FakeProfitBackend
    ) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)
        assert fake_backend.set_price_depth_cb_calls >= 1
        client.disconnect()


class TestPriceDepthCallback:
    def _make_asset(self) -> TConnectorAssetIdentifier:
        asset = TConnectorAssetIdentifier()
        asset.Version = 0
        asset.Ticker = "PETR4"
        asset.Exchange = "B"
        asset.FeedType = 0
        return asset

    def test_edit_update_delivered(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[PriceLevel] = []
        ready = threading.Event()

        @client.on(Event.PRICE_LEVEL)
        def on_level(level: PriceLevel) -> None:
            received.append(level)
            ready.set()

        asset = self._make_asset()
        client._dispatcher.start()
        fake_backend.price_depth_callback(asset, int(BookSide.BUY), 0, int(BookUpdateType.EDIT))

        assert ready.wait(timeout=2.0)
        client.stop()

        assert len(received) == 1
        lvl = received[0]
        assert lvl.position == 0
        assert lvl.side is BookSide.BUY
        assert lvl.update_type is BookUpdateType.EDIT

    def test_edit_update_accessor_failure_falls_back_to_zeros(
        self, fake_backend: FakeProfitBackend
    ) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[PriceLevel] = []
        ready = threading.Event()

        @client.on(Event.PRICE_LEVEL)
        def on_level(level: PriceLevel) -> None:
            received.append(level)
            ready.set()

        fake_backend.get_price_group_result = int(NLCode.NOT_FOUND)

        asset = self._make_asset()
        client._dispatcher.start()
        fake_backend.price_depth_callback(asset, int(BookSide.BUY), 0, int(BookUpdateType.EDIT))

        assert ready.wait(timeout=2.0)
        client.stop()

        lvl = received[0]
        assert lvl.update_type is BookUpdateType.EDIT
        assert lvl.price == 0.0
        assert lvl.quantity == 0

    def test_public_get_price_group(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        group = TConnectorPriceGroup()
        group.Version = 0
        group.Price = 28.50
        group.Count = 5
        group.Quantity = 1000
        group.PriceGroupFlags = PG_IS_THEORIC
        fake_backend.queue_price_group("PETR4", int(BookSide.BUY), 0, group)

        level = client.get_price_group("PETR4", BookSide.BUY, 0, exchange="B")
        assert level.price == 28.50
        assert level.quantity == 1000
        assert level.count == 5
        client.disconnect()

    def test_delete_update_no_accessor(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[PriceLevel] = []
        ready = threading.Event()

        @client.on(Event.PRICE_LEVEL)
        def on_level(level: PriceLevel) -> None:
            received.append(level)
            ready.set()

        # Um nível existe na posição 2: se o handler consultasse a DLL para
        # DELETE, o preço viria preenchido — o contrato é não consultar.
        group = TConnectorPriceGroup()
        group.Version = 0
        group.Price = 28.50
        fake_backend.queue_price_group("PETR4", int(BookSide.BUY), 2, group)

        asset = self._make_asset()
        client._dispatcher.start()
        fake_backend.price_depth_callback(asset, int(BookSide.BUY), 2, int(BookUpdateType.DELETE))

        assert ready.wait(timeout=2.0)
        client.stop()

        assert received[0].update_type is BookUpdateType.DELETE
        assert received[0].position == 2
        assert received[0].price == 0.0

    def test_edit_update_reads_price_group(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[PriceLevel] = []
        ready = threading.Event()

        @client.on(Event.PRICE_LEVEL)
        def on_level(level: PriceLevel) -> None:
            received.append(level)
            ready.set()

        group = TConnectorPriceGroup()
        group.Version = 0
        group.Price = 28.50
        group.Count = 5
        group.Quantity = 1000
        group.PriceGroupFlags = PG_IS_THEORIC
        fake_backend.queue_price_group("PETR4", int(BookSide.BUY), 0, group)

        asset = self._make_asset()
        client._dispatcher.start()
        fake_backend.price_depth_callback(asset, int(BookSide.BUY), 0, int(BookUpdateType.EDIT))

        assert ready.wait(timeout=2.0)
        client.stop()

        lvl = received[0]
        assert lvl.price == 28.50
        assert lvl.count == 5
        assert lvl.quantity == 1000
        assert lvl.is_theoretical is True

    def test_full_book_snapshot_reads_levels(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[PriceBookSnapshot] = []
        ready = threading.Event()

        @client.on(Event.PRICE_SNAPSHOT)
        def on_snapshot(snap: PriceBookSnapshot) -> None:
            received.append(snap)
            ready.set()

        for pos, price in enumerate((37.10, 37.09, 37.05)):
            group = TConnectorPriceGroup()
            group.Version = 0
            group.Price = price
            group.Count = pos + 1
            group.Quantity = (pos + 1) * 100
            fake_backend.queue_price_group("PETR4", int(BookSide.BUY), pos, group)

        sell = TConnectorPriceGroup()
        sell.Version = 0
        sell.Price = 37.20
        sell.Count = 1
        sell.Quantity = 500
        sell.PriceGroupFlags = PG_IS_THEORIC
        fake_backend.queue_price_group("PETR4", int(BookSide.SELL), 0, sell)

        fake_backend.set_price_side_count("PETR4", int(BookSide.BUY), 3)
        fake_backend.set_price_side_count("PETR4", int(BookSide.SELL), 1)

        asset = self._make_asset()
        client._dispatcher.start()
        fake_backend.price_depth_callback(
            asset, int(BookSide.BUY), 0, int(BookUpdateType.FULL_BOOK)
        )

        assert ready.wait(timeout=2.0)
        client.stop()

        snap = received[0]
        assert [lvl.price for lvl in snap.buy_levels] == [37.10, 37.09, 37.05]
        assert [lvl.position for lvl in snap.buy_levels] == [0, 1, 2]
        assert all(lvl.side is BookSide.BUY for lvl in snap.buy_levels)
        assert all(lvl.update_type is BookUpdateType.FULL_BOOK for lvl in snap.buy_levels)
        assert snap.buy_levels[0].count == 1
        assert snap.buy_levels[0].quantity == 100

        assert len(snap.sell_levels) == 1
        sell_lvl = snap.sell_levels[0]
        assert sell_lvl.price == 37.20
        assert sell_lvl.side is BookSide.SELL
        assert sell_lvl.quantity == 500
        assert sell_lvl.is_theoretical is True

    def test_full_book_caps_levels_at_bound(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[PriceBookSnapshot] = []
        ready = threading.Event()

        @client.on(Event.PRICE_SNAPSHOT)
        def on_snapshot(snap: PriceBookSnapshot) -> None:
            received.append(snap)
            ready.set()

        fake_backend.set_price_side_count("PETR4", int(BookSide.BUY), 60)
        fake_backend.set_price_side_count("PETR4", int(BookSide.SELL), 0)

        asset = self._make_asset()
        client._dispatcher.start()
        fake_backend.price_depth_callback(
            asset, int(BookSide.BUY), 0, int(BookUpdateType.FULL_BOOK)
        )

        assert ready.wait(timeout=2.0)
        client.stop()

        snap = received[0]
        assert len(snap.buy_levels) == 50
        assert snap.sell_levels == ()

    def test_full_book_emits_snapshot(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[PriceBookSnapshot] = []
        ready = threading.Event()

        @client.on(Event.PRICE_SNAPSHOT)
        def on_snapshot(snap: PriceBookSnapshot) -> None:
            received.append(snap)
            ready.set()

        asset = self._make_asset()
        client._dispatcher.start()
        fake_backend.price_depth_callback(
            asset, int(BookSide.BUY), 0, int(BookUpdateType.FULL_BOOK)
        )

        assert ready.wait(timeout=2.0)
        client.stop()

        snap = received[0]
        assert snap.buy_levels == ()
        assert snap.sell_levels == ()


class TestDailyCallback:
    def test_daily_delivered(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        received: list[DailyCandle] = []
        ready = threading.Event()

        @client.on(Event.DAILY)
        def on_daily(candle: DailyCandle) -> None:
            received.append(candle)
            ready.set()

        asset_legacy = TAssetID()
        asset_legacy.ticker = "WDOFUT"
        asset_legacy.bolsa = "F"
        asset_legacy.feed = 0

        client._dispatcher.start()
        fake_backend.emit_daily(
            asset_legacy,
            "31/07/2026 18:00:00.000",
            5120.0,
            5150.0,
            5100.0,
            5130.5,
            1000000.0,
            5100.0,
            5400.0,
            4900.0,
            600000.0,
            400000.0,
            200,
            50,
            10000,
            120,
            80,
            30,
            20,
        )

        assert ready.wait(timeout=2.0)
        client.stop()

        d = received[0]
        assert d.asset.ticker == "WDOFUT"
        assert d.asset.exchange == "F"
        assert d.open == 5120.0
        assert d.close == 5130.5
        assert d.open_interest == 10000
        assert d.date == "31/07/2026 18:00:00.000"


class TestMarketWarnings:
    def test_partial_connected_logged_not_fatal(
        self, fake_backend: FakeProfitBackend, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        with caplog.at_level("CRITICAL", logger="profitdll_wrapper.client"):
            fake_backend.emit_state(
                ConnectionState.MARKET_DATA, int(MarketResult.PARTIAL_CONNECTED)
            )

        assert any("frozen (6)" in r.message for r in caplog.records)
        client.disconnect()

    def test_performance_warning_logged(
        self, fake_backend: FakeProfitBackend, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = _client(fake_backend)
        client.connect(timeout=2.0)

        with caplog.at_level("WARNING", logger="profitdll_wrapper.client"):
            fake_backend.emit_state(
                ConnectionState.MARKET_DATA, int(MarketResult.PERFORMANCE_WARNING)
            )

        assert any("degradation" in r.message for r in caplog.records)
        client.disconnect()


class TestReadTheoreticalPrice:
    def test_returns_theoretical_price_when_valid(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        fake_backend.set_theoretical_price("WDOFUT", 5130.0, 100)
        asset = TConnectorAssetIdentifier(Version=0, Ticker="WDOFUT", Exchange="F", FeedType=0)

        assert client._read_theoretical_price(asset) == 5130.0

    def test_returns_none_when_neg_inf(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        asset = TConnectorAssetIdentifier(Version=0, Ticker="DOLU26", Exchange="F", FeedType=0)

        assert client._read_theoretical_price(asset) is None

    def test_returns_none_when_nan(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        fake_backend.set_theoretical_price("PETR4", float("nan"), 0)
        asset = TConnectorAssetIdentifier(Version=0, Ticker="PETR4", Exchange="B", FeedType=0)

        assert client._read_theoretical_price(asset) is None

    def test_returns_none_when_zero_or_negative(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        fake_backend.set_theoretical_price("PETR4", 0.0, 0)
        asset = TConnectorAssetIdentifier(Version=0, Ticker="PETR4", Exchange="B", FeedType=0)

        assert client._read_theoretical_price(asset) is None

    def test_returns_none_when_backend_fails(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        fake_backend.get_theoretical_result = int(NLCode.INVALID_TICKER)
        asset = TConnectorAssetIdentifier(Version=0, Ticker="BAD", Exchange="B", FeedType=0)

        assert client._read_theoretical_price(asset) is None


class TestRequestTickerInfo:
    def test_request_ticker_info_and_event(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        infos_received: list[AssetInfo] = []

        @client.on(Event.ASSET_INFO)
        def _on_info(info: AssetInfo) -> None:
            infos_received.append(info)

        client.connect(timeout=2.0)

        client.request_ticker_info("PETR4", exchange="B")
        assert fake_backend.requested_ticker_info == [("PETR4", "B")]

        raw_asset = TAssetID(ticker="PETR4", bolsa="B")
        fake_backend.emit_asset_info(
            raw_asset,
            name="PETROBRAS PN",
            description="PETROLEO BRASILEIRO S.A. PETROBRAS",
            min_qty=100,
            max_qty=100000,
            lot=100,
            sec_type=1,
            sub_type=0,
            min_inc=0.01,
            mult=1.0,
            valid_date="",
            isin="BRPETRACNPR6",
            sector="Petróleo, Gás e Biocombustíveis",
            subsector="Petróleo, Gás e Biocombustíveis",
            segment="Exploração, Refino e Distribuição",
        )

        time.sleep(0.1)

        assert len(infos_received) == 1
        info = infos_received[0]
        assert info.asset.ticker == "PETR4"
        assert info.asset.exchange == "B"
        assert info.name == "PETROBRAS PN"
        assert info.lot_size == 100
        assert info.min_price_increment == 0.01
        assert info.isin == "BRPETRACNPR6"
        assert info.sector == "Petróleo, Gás e Biocombustíveis"

    def test_request_ticker_info_invalid_exchange(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        with pytest.raises(ValueError):
            client.request_ticker_info("PETR4", exchange="Z")


class TestChangeStateTicker:
    def test_change_state_ticker_event(self, fake_backend: FakeProfitBackend) -> None:
        client = _client(fake_backend)
        changes_received: list[TickerStateChange] = []

        @client.on(Event.TICKER_STATE)
        def _on_state(change: TickerStateChange) -> None:
            changes_received.append(change)

        client.connect(timeout=2.0)

        raw_asset = TAssetID(ticker="PETR4", bolsa="B")
        fake_backend.emit_change_state_ticker(raw_asset, "03/08/2026 17:00:00.000", 4)

        time.sleep(0.1)

        assert len(changes_received) == 1
        ch = changes_received[0]
        assert ch.asset.ticker == "PETR4"
        assert ch.asset.exchange == "B"
        assert ch.date == "03/08/2026 17:00:00.000"
        assert ch.state == TickerState.AUCTIONED
        assert ch.raw_state == 4
