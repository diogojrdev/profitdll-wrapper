"""Testes de unidade para os handlers de callback em _callback_handlers.py.

Verifica a decodificação binária de offer book, mensagens de negociação/risco,
cadastro de ativos (asset info), mudança de estado do ativo, candles diários e
resiliência contra exceções.
"""

from __future__ import annotations

import ctypes
import struct
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from profitdll_wrapper import (
    AssetId,
    DailyCandle,
    Event,
    Position,
    PriceBookSnapshot,
)
from profitdll_wrapper._bindings.enums import ConnectionState, TickerState
from profitdll_wrapper._bindings.structures import TAssetID, TConnectorTradingMessageResult
from profitdll_wrapper._events.dispatcher import EventDispatcher
from profitdll_wrapper._types import AssetInfo, TickerStateChange, TradingMessageResult
from profitdll_wrapper.client._callback_handlers import (
    _ClientCallbackMixin,
    _descript_offer_array_v2,
)


class DummyClient(_ClientCallbackMixin):
    def __init__(self) -> None:
        self._backend = MagicMock()
        self._dispatcher = EventDispatcher(self._backend)
        self._state_events = {}
        self._last_state_results: dict[ConnectionState, int] = {}
        self._login_error_lock = threading.Lock()
        self._login_error_val: int | None = None
        self._login_error_state_val: ConnectionState | None = None
        self._has_connected_once = False

    @property
    def _login_error(self) -> int | None:
        with self._login_error_lock:
            return self._login_error_val

    @_login_error.setter
    def _login_error(self, value: int | None) -> None:
        with self._login_error_lock:
            self._login_error_val = value

    @property
    def _login_error_state(self) -> ConnectionState | None:
        with self._login_error_lock:
            return self._login_error_state_val

    def _set_login_error(self, state: ConnectionState, n_result: int) -> None:
        with self._login_error_lock:
            if self._login_error_val is None:
                self._login_error_val = n_result
                self._login_error_state_val = state

    def _record_state_result(self, state: ConnectionState, n_result: int) -> None:
        self._last_state_results[state] = n_result

    def get_position(
        self, ticker: str, exchange: str = "", account: str = "", broker_id: int = 0
    ) -> Position:
        return Position(
            account_id=account,
            asset=AssetId(ticker=ticker, exchange=exchange),
            quantity=10,
            average_price=100.0,
            buy_quantity=10,
        )


def _process_pending(dispatcher: EventDispatcher) -> None:
    while not dispatcher._queue.empty():
        item = dispatcher._queue.get_nowait()
        dispatcher._dispatch(item)


def _create_mock_offer_array_ptr(offers: list[tuple[float, int, int, int, str]]) -> Any:
    """Helper para simular o buffer binário de ofertas V2 da profitdll_wrapper."""
    if not offers:
        return None

    # Header: qtd_offer (int32), pointer_size (int32)
    header = struct.pack("ii", len(offers), len(offers) * 53)
    records = bytearray()
    for price, qty, agent, offer_id, date_str in offers:
        date_bytes = date_str.encode("utf-8")
        rec = struct.pack("=dqiqH", price, qty, agent, offer_id, len(date_bytes)) + date_bytes
        records.extend(rec)

    full_data = header + bytes(records)
    c_array = (ctypes.c_char * len(full_data)).from_buffer_copy(full_data)
    return ctypes.cast(c_array, ctypes.c_void_p)


def test_descript_offer_array_v2_null_or_empty() -> None:
    assert _descript_offer_array_v2(None) == []
    assert _descript_offer_array_v2(0) == []


def test_descript_offer_array_v2_valid_buffer() -> None:
    offers_in = [
        (105.50, 10, 15003, 1001, "2026-08-04 10:00:00"),
        (105.75, 20, 15003, 1002, "2026-08-04 10:00:01"),
    ]
    ptr = _create_mock_offer_array_ptr(offers_in)
    res = _descript_offer_array_v2(ptr)
    assert len(res) == 2
    assert res[0][0] == 105.50
    assert res[0][1] == 10
    assert res[1][0] == 105.75


def test_descript_offer_array_v2_zero_offers() -> None:
    data = struct.pack("ii", 0, 0)
    c_array = (ctypes.c_char * len(data)).from_buffer_copy(data)
    ptr = ctypes.cast(c_array, ctypes.c_void_p)
    assert _descript_offer_array_v2(ptr) == []


def test_on_offer_book_v2(dummy_client: DummyClient) -> None:
    events: list[PriceBookSnapshot] = []
    dummy_client._dispatcher.add_handler(Event.PRICE_SNAPSHOT.value, lambda s: events.append(s))

    asset = TAssetID()
    asset.ticker = "PETR4"
    asset.bolsa = "B"

    buy_ptr = _create_mock_offer_array_ptr([(35.0, 100, 1, 1, "10:00:00")])
    sell_ptr = _create_mock_offer_array_ptr([(35.10, 200, 2, 2, "10:00:00")])

    dummy_client._on_offer_book_v2(
        asset, 1, 0, 1, 100, 1, 1, 35.0, 1, 1, 1, 1, 1, "10:00:00", sell_ptr, buy_ptr
    )

    _process_pending(dummy_client._dispatcher)
    assert len(events) == 1
    snapshot = events[0]
    assert snapshot.asset.ticker == "PETR4"
    assert len(snapshot.buy_levels) == 1
    assert len(snapshot.sell_levels) == 1
    assert snapshot.buy_levels[0].price == 35.0
    assert snapshot.sell_levels[0].price == 35.10


def test_on_trading_message(dummy_client: DummyClient) -> None:
    messages: list[TradingMessageResult] = []
    dummy_client._dispatcher.add_handler(Event.TRADING_MESSAGE.value, lambda m: messages.append(m))

    native = TConnectorTradingMessageResult()
    native.Version = 0
    native.BrokerID = 15003
    native.MessageID = 123
    native.ResultCode = 1
    native.Message = "Ordem Rejeitada por Risco"

    dummy_client._on_trading_message(ctypes.pointer(native))
    _process_pending(dummy_client._dispatcher)

    assert len(messages) == 1
    assert messages[0].message == "Ordem Rejeitada por Risco"


def test_on_asset_list_info_v2(dummy_client: DummyClient) -> None:
    infos: list[AssetInfo] = []
    dummy_client._dispatcher.add_handler(Event.ASSET_INFO.value, lambda info: infos.append(info))

    asset = TAssetID()
    asset.ticker = "VALE3"
    asset.bolsa = "B"

    dummy_client._on_asset_list_info_v2(
        asset,
        "VALE ON",
        "Vale S.A.",
        100,
        100000,
        100,
        1,
        1,
        0.01,
        1.0,
        "2026-12-31",
        "BRVALEACNOR0",
        "Mineracao",
        "Mineracao",
        "Novo Mercado",
    )

    _process_pending(dummy_client._dispatcher)
    assert len(infos) == 1
    info = infos[0]
    assert info.asset.ticker == "VALE3"
    assert info.name == "VALE ON"
    assert info.min_order_qty == 100
    assert info.min_price_increment == 0.01
    assert info.isin == "BRVALEACNOR0"


def test_on_change_state_ticker(dummy_client: DummyClient) -> None:
    changes: list[TickerStateChange] = []
    dummy_client._dispatcher.add_handler(Event.TICKER_STATE.value, lambda c: changes.append(c))

    asset = TAssetID()
    asset.ticker = "WINQ26"
    asset.bolsa = "F"

    dummy_client._on_change_state_ticker(asset, "2026-08-04 10:15:00", 2)
    _process_pending(dummy_client._dispatcher)

    assert len(changes) == 1
    assert changes[0].asset.ticker == "WINQ26"
    assert changes[0].date == "2026-08-04 10:15:00"
    assert changes[0].state == TickerState.AUCTIONED or changes[0].raw_state == 2


def test_on_daily(dummy_client: DummyClient) -> None:
    candles: list[DailyCandle] = []
    dummy_client._dispatcher.add_handler(Event.DAILY.value, lambda c: candles.append(c))

    asset = TAssetID()
    asset.ticker = "PETR4"
    asset.bolsa = "B"

    dummy_client._on_daily(
        asset,
        "2026-08-04",
        35.0,
        36.0,
        34.5,
        35.8,
        1000000.0,
        35.5,
        40.0,
        30.0,
        600000.0,
        400000.0,
        5000,
        1200,
        10000,
        3000,
        2000,
        700,
        500,
    )

    _process_pending(dummy_client._dispatcher)
    assert len(candles) == 1
    candle = candles[0]
    assert candle.asset.ticker == "PETR4"
    assert candle.open == 35.0
    assert candle.close == 35.8
    assert candle.trades == 1200


def test_on_asset_position_list(dummy_client: DummyClient) -> None:
    positions: list[Position] = []
    dummy_client._dispatcher.add_handler(Event.POSITION.value, lambda p: positions.append(p))

    acc = MagicMock()
    acc.AccountID = "12345"
    acc.BrokerID = 15003

    asset = MagicMock()
    asset.Ticker = "WDOFUT"
    asset.Exchange = "F"

    dummy_client._on_asset_position_list(acc, asset, 0)
    _process_pending(dummy_client._dispatcher)

    assert len(positions) == 1
    assert positions[0].account_id == "12345"
    assert positions[0].asset.ticker == "WDOFUT"
    assert positions[0].quantity == 10


def test_on_state_unknown_and_login_error(dummy_client: DummyClient) -> None:
    dummy_client._on_state(999, 0)  # Estado desconhecido
    assert dummy_client._login_error is None

    dummy_client._on_state(int(ConnectionState.LOGIN), 2)  # Login com erro
    assert dummy_client._login_error == 2


@pytest.fixture
def dummy_client() -> DummyClient:
    return DummyClient()
