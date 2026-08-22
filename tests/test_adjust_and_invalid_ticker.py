"""Testes unitários para a Fase 3 do roadmap: SubscribeAdjustHistory e SetInvalidTickerCallback."""

from __future__ import annotations

import time

import pytest

from profitdll_wrapper import AdjustHistory, Event, InvalidTickerEvent, ProfitClient
from profitdll_wrapper._bindings.enums import MARKET_DATA_STATES
from profitdll_wrapper._bindings.structures import TAssetID
from tests.fakes.backend import FakeProfitBackend


@pytest.fixture
def fake_backend() -> FakeProfitBackend:
    backend = FakeProfitBackend()
    backend.connect_states = MARKET_DATA_STATES
    return backend


@pytest.fixture
def client(fake_backend: FakeProfitBackend) -> ProfitClient:
    return ProfitClient(
        activation_key="fake_key",
        user="fake_user",
        password="fake_password",
        mode="market_data",
        backend=fake_backend,
    )


def test_subscribe_unsubscribe_adjust_history(
    client: ProfitClient, fake_backend: FakeProfitBackend
) -> None:
    with client:
        client.subscribe_adjust_history("PETR4", exchange="B")
        assert ("PETR4", "B") in fake_backend.subscribed_adjust_history

        client.unsubscribe_adjust_history("PETR4", exchange="B")
        assert ("PETR4", "B") not in fake_backend.subscribed_adjust_history


def test_adjust_history_event_callback(
    client: ProfitClient, fake_backend: FakeProfitBackend
) -> None:
    adjusts: list[AdjustHistory] = []

    @client.on(Event.ADJUST_HISTORY)
    def on_adjust(adj: AdjustHistory) -> None:
        adjusts.append(adj)

    with client:
        asset = TAssetID()
        asset.pwcTicker = "PETR4"
        asset.pwcBolsa = "B"

        fake_backend.emit_adjust_history(
            asset_id=asset,
            value=1.75,
            adjust_type="DIVIDENDO",
            observation="Aprovado em AGO",
            adjust_date="01/08/2026",
            deliberation_date="30/07/2026",
            payment_date="20/08/2026",
            affect_price=True,
        )
        time.sleep(0.1)

        assert len(adjusts) == 1
        assert adjusts[0].asset.ticker == "PETR4"
        assert adjusts[0].value == 1.75
        assert adjusts[0].adjust_type == "DIVIDENDO"
        assert adjusts[0].observation == "Aprovado em AGO"
        assert adjusts[0].payment_date == "20/08/2026"
        assert adjusts[0].affect_price is True


def test_invalid_ticker_event_callback(
    client: ProfitClient, fake_backend: FakeProfitBackend
) -> None:
    invalid_events: list[InvalidTickerEvent] = []

    @client.on(Event.INVALID_TICKER)
    def on_invalid(evt: InvalidTickerEvent) -> None:
        invalid_events.append(evt)

    with client:
        fake_backend.emit_invalid_ticker("BOGUS99", exchange="B")
        time.sleep(0.1)

        assert len(invalid_events) == 1
        assert invalid_events[0].asset.ticker == "BOGUS99"
        assert invalid_events[0].asset.exchange == "B"
