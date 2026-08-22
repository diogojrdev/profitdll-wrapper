"""Testes do EventDispatcher: enfileiramento, isolamento de erros, ordem."""

from __future__ import annotations

import threading
import time

from profitdll_wrapper import AssetId, Trade
from profitdll_wrapper._events.dispatcher import ErrorEvent, EventDispatcher


class _FakeBackend:
    """Backend mínimo — o dispatcher não chama a DLL diretamente nos testes."""

    # Satisfaz apenas a tipagem; métodos não usados aqui.
    pass


def _make_trade(price: float = 100.0, number: int = 1) -> Trade:
    import datetime

    return Trade(
        asset=AssetId(ticker="WDOFUT", exchange="F"),
        trade_number=number,
        price=price,
        quantity=5,
        volume=price * 5,
        buy_agent=1,
        sell_agent=2,
        trade_type=2,
        timestamp=datetime.datetime(2026, 7, 31, 10, 0, 0),
        is_edit=False,
    )


def test_trade_delivered_to_handler() -> None:
    disp = EventDispatcher(backend=_FakeBackend())  # type: ignore[arg-type]
    received: list[Trade] = []
    ready = threading.Event()

    @disp.on("TRADE")
    def handler(item: Trade) -> None:
        received.append(item)
        ready.set()

    with disp:
        disp.enqueue_trade(_make_trade(price=42.0))
        assert ready.wait(timeout=2.0)

    assert len(received) == 1
    assert received[0].price == 42.0


def test_handler_exception_does_not_propagate() -> None:
    disp = EventDispatcher(backend=_FakeBackend())  # type: ignore[arg-type]
    good_received: list[Trade] = []
    second_trade_delivered = threading.Event()

    @disp.on("TRADE")
    def bad_handler(_: Trade) -> None:
        raise RuntimeError("handler broken")

    @disp.on("TRADE")
    def good_handler(item: Trade) -> None:
        good_received.append(item)
        second_trade_delivered.set()

    with disp:
        disp.enqueue_trade(_make_trade(number=1))
        assert second_trade_delivered.wait(timeout=2.0)

    # O segundo handler ainda deve rodar apesar da falha do primeiro.
    assert len(good_received) == 1


def test_error_event_routed_to_error_handler() -> None:
    disp = EventDispatcher(backend=_FakeBackend())  # type: ignore[arg-type]
    errors: list[ErrorEvent] = []
    error_received = threading.Event()

    @disp.on("ERROR")
    def on_error(err: ErrorEvent) -> None:
        errors.append(err)
        error_received.set()

    @disp.on("TRADE")
    def bad_handler(_: Trade) -> None:
        raise ValueError("boom")

    with disp:
        disp.enqueue_trade(_make_trade())
        assert error_received.wait(timeout=2.0)

    assert len(errors) == 1
    assert isinstance(errors[0].exception, ValueError)


def test_order_preserved() -> None:
    disp = EventDispatcher(backend=_FakeBackend())  # type: ignore[arg-type]
    prices: list[float] = []
    done = threading.Event()
    count = {"n": 0}

    @disp.on("TRADE")
    def handler(item: Trade) -> None:
        prices.append(item.price)
        count["n"] += 1
        if count["n"] == 5:
            done.set()

    with disp:
        for i in range(5):
            disp.enqueue_trade(_make_trade(price=float(i), number=i))
        assert done.wait(timeout=3.0)

    assert prices == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_stop_is_idempotent_and_clean() -> None:
    disp = EventDispatcher(backend=_FakeBackend())  # type: ignore[arg-type]
    disp.start()
    time.sleep(0.05)
    disp.stop()
    # Segunda chamada não deve levantar.
    disp.stop()
