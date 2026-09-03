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


def test_remove_handler_stops_delivery() -> None:
    disp = EventDispatcher(backend=_FakeBackend())  # type: ignore[arg-type]
    received: list[Trade] = []
    first = threading.Event()

    def handler(item: Trade) -> None:
        received.append(item)
        first.set()

    disp.add_handler("TRADE", handler)
    disp.start()
    try:
        disp.enqueue_trade(_make_trade(number=1))
        assert first.wait(timeout=2.0)

        disp.remove_handler("TRADE", handler)
        after = threading.Event()
        disp.add_handler("TRADE", lambda _item: after.set())
        disp.enqueue_trade(_make_trade(number=2))
        assert after.wait(timeout=2.0)

        # O handler removido não roda mais: continua 1 entrega.
        assert len(received) == 1
    finally:
        disp.stop()


def test_remove_handler_is_idempotent() -> None:
    disp = EventDispatcher(backend=_FakeBackend())  # type: ignore[arg-type]

    def handler(_: Trade) -> None:
        pass

    # Remover handler nunca registrado, de evento desconhecido ou duas vezes
    # não deve levantar (idempotência do contrato do off()).
    disp.remove_handler("TRADE", handler)
    disp.remove_handler("UNKNOWN_EVENT", handler)
    disp.add_handler("TRADE", handler)
    disp.remove_handler("TRADE", handler)
    disp.remove_handler("TRADE", handler)


def test_remove_handler_removes_one_occurrence_per_call() -> None:
    disp = EventDispatcher(backend=_FakeBackend())  # type: ignore[arg-type]
    received: list[Trade] = []
    delivered_twice = threading.Event()
    count = {"n": 0}

    def handler(item: Trade) -> None:
        received.append(item)
        count["n"] += 1
        if count["n"] == 2:
            delivered_twice.set()

    # Registro duplicado = entrega dupla (comportamento atual do on()).
    disp.add_handler("TRADE", handler)
    disp.add_handler("TRADE", handler)
    disp.start()
    try:
        disp.enqueue_trade(_make_trade(number=1))
        assert delivered_twice.wait(timeout=2.0)

        # Uma remoção remove uma ocorrência: a segunda continua ativa.
        disp.remove_handler("TRADE", handler)
        count["n"] = 0
        again = threading.Event()

        def second(_: Trade) -> None:
            again.set()

        disp.add_handler("TRADE", second)
        disp.enqueue_trade(_make_trade(number=2))
        assert again.wait(timeout=2.0)
        assert count["n"] == 1
    finally:
        disp.stop()


def test_stop_run_unblocks_run_without_stopping_dispatch() -> None:
    disp = EventDispatcher(backend=_FakeBackend())  # type: ignore[arg-type]
    disp.start()

    run_exited = threading.Event()

    def run_thread() -> None:
        disp.run()
        run_exited.set()

    thread = threading.Thread(target=run_thread, daemon=True)
    thread.start()
    time.sleep(0.3)

    # O dispatcher ainda deve estar bombeando após stop_run().
    disp.stop_run()
    assert run_exited.wait(timeout=2.0)

    received = threading.Event()
    disp.add_handler("TRADE", lambda _item: received.set())
    disp.enqueue_trade(_make_trade())
    assert received.wait(timeout=2.0), "dispatch thread should still pump after stop_run()"

    disp.stop()
