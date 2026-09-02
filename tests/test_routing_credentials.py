"""Testes de regressão do incidente de envio de ordens (26/08/2026).

Cobre os achados do diagnóstico do incidente:

* P0-1 — a senha de roteamento (``ROUTING_KEY``) é carregada pelo ``_config``
  e usada nas chamadas de roteamento, nunca a senha de login;
* P0-2 — ``StopPrice = -1`` em ordens não-stop (manual, ``SendOrder``);
* P1-3 — ``Version = 0`` em ``SendCancelOrderV2``/``SendChangeOrderV2``
  (manual: "Supported: 0");
* P1-4 — mapeamento de status do histórico de ordens ≡ ``OrderStatus``
  (1=PartiallyFilled, 2=Filled, 4=Canceled, 8=Rejected);
* mapeamento ``mrc`` (``TConnectorTradingMessageResultCode``) da cadeia de
  aceite de ordens.

Nenhum teste carrega a DLL real: tudo via ``FakeProfitBackend``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from profitdll_wrapper import OrderStatus, ProfitClient, TradingMessageResultCode
from profitdll_wrapper._bindings.enums import ROUTING_STATES
from profitdll_wrapper._bindings.structures import TConnectorOrder
from profitdll_wrapper._config import load_credentials
from tests.fakes.backend import FakeProfitBackend

ROUTING_PASSWORD = "routing-pass"
LOGIN_PASSWORD = "login-pass"


@pytest.fixture
def backend() -> FakeProfitBackend:
    backend = FakeProfitBackend()
    backend.connect_states = ROUTING_STATES
    return backend


@pytest.fixture
def client(backend: FakeProfitBackend) -> ProfitClient:
    return ProfitClient(
        activation_key="key",
        user="user",
        password=LOGIN_PASSWORD,
        routing_password=ROUTING_PASSWORD,
        mode="routing",
        backend=backend,
        broker_id=15003,
    )


def _routing_call(backend: FakeProfitBackend, method: str) -> dict:
    calls = [c for c in backend.routing_calls if c["method"] == method]
    assert calls, f"no {method} call captured; got: {backend.routing_calls}"
    return calls[-1]


# --------------------------------------------------------------------------- #
# P0-1 — carregamento da ROUTING_KEY (._config)
# --------------------------------------------------------------------------- #
class TestRoutingKeyConfig:
    def test_routing_key_loaded_from_env_file(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("PASSWORD=login-secret\nROUTING_KEY=routing-secret\n", encoding="utf-8")
        creds = load_credentials(env)
        assert creds["password"] == "login-secret"
        assert creds["routing_key"] == "routing-secret"

    def test_prefixed_env_var_takes_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = tmp_path / ".env"
        env.write_text("ROUTING_KEY=file-routing\n", encoding="utf-8")
        monkeypatch.setenv("PROFITDLL_ROUTING_KEY", "env-routing")
        assert load_credentials(env)["routing_key"] == "env-routing"

    def test_missing_routing_key_is_empty_and_never_falls_back_to_login(
        self, tmp_path: Path
    ) -> None:
        """Sem ROUTING_KEY o loader devolve vazio — o fallback (se houver) é
        decisão da camada de aplicação, nunca silencioso na biblioteca."""
        env = tmp_path / ".env"
        env.write_text("PASSWORD=login-secret\n", encoding="utf-8")
        assert load_credentials(env)["routing_key"] == ""

    def test_generic_os_password_env_does_not_leak_as_routing_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PASSWORD", "os-password")
        assert load_credentials(tmp_path / ".env-missing")["routing_key"] == ""


# --------------------------------------------------------------------------- #
# P0-1 — guarda do ProfitClient e resolução da senha de roteamento
# --------------------------------------------------------------------------- #
class TestRoutingPasswordGuard:
    def test_routing_mode_requires_routing_password(self, backend: FakeProfitBackend) -> None:
        with pytest.raises(ValueError, match="routing_password"):
            ProfitClient(
                activation_key="key",
                user="user",
                password=LOGIN_PASSWORD,
                mode="routing",
                backend=backend,
                broker_id=15003,
            )

    def test_market_data_mode_does_not_require_routing_password(
        self, fake_backend: FakeProfitBackend
    ) -> None:
        client = ProfitClient(
            activation_key="key",
            user="user",
            password=LOGIN_PASSWORD,
            backend=fake_backend,
            broker_id=15003,
        )
        with client:
            assert client.is_connected

    def test_routing_call_without_any_password_raises(
        self, fake_backend: FakeProfitBackend
    ) -> None:
        client = ProfitClient(
            activation_key="key",
            user="user",
            password=LOGIN_PASSWORD,
            backend=fake_backend,
            broker_id=15003,
        )
        with pytest.raises(ValueError, match="routing password not set"):
            client.send_buy_order("PETR4", exchange="B", account="12345", price=38.5, quantity=100)


class TestRoutingPasswordUsage:
    def test_send_order_uses_client_routing_password_by_default(
        self, client: ProfitClient, backend: FakeProfitBackend
    ) -> None:
        with client:
            client.send_buy_order("PETR4", exchange="B", account="12345", price=38.5, quantity=100)
        assert _routing_call(backend, "send_order")["password"] == ROUTING_PASSWORD

    def test_send_order_explicit_password_overrides_client_default(
        self, client: ProfitClient, backend: FakeProfitBackend
    ) -> None:
        with client:
            client.send_buy_order(
                "PETR4",
                exchange="B",
                account="12345",
                price=38.5,
                quantity=100,
                password="explicit-routing",
            )
        assert _routing_call(backend, "send_order")["password"] == "explicit-routing"

    def test_login_password_is_not_used_as_routing_password(
        self, client: ProfitClient, backend: FakeProfitBackend
    ) -> None:
        """Regressão do incidente: a senha capturada nunca é a de login."""
        with client:
            client.send_buy_order("PETR4", exchange="B", account="12345", price=38.5, quantity=100)
            client.send_market_sell("PETR4", exchange="B", account="12345", quantity=100)
        passwords = {c["password"] for c in backend.routing_calls}
        assert passwords == {ROUTING_PASSWORD}
        assert LOGIN_PASSWORD not in passwords

    def test_all_routing_calls_default_to_client_password(
        self, client: ProfitClient, backend: FakeProfitBackend
    ) -> None:
        with client:
            client.cancel_order("12345", 1001)
            client.change_order("12345", 1001, price=39.0, quantity=100)
            client.cancel_all_orders("12345", "PETR4", exchange="B")
            client.cancel_all_account_orders("12345")
            client.zero_position("PETR4", exchange="B", account="12345")
        for call in backend.routing_calls:
            assert call["password"] == ROUTING_PASSWORD, call


# --------------------------------------------------------------------------- #
# P0-2 / P1-3 — conformidade de campos com o manual (StopPrice, Version)
# --------------------------------------------------------------------------- #
class TestStructFieldsPerManual:
    def test_send_limit_order_stop_price_minus_one(
        self, client: ProfitClient, backend: FakeProfitBackend
    ) -> None:
        with client:
            client.send_buy_order("PETR4", exchange="B", account="12345", price=38.5, quantity=100)
        call = _routing_call(backend, "send_order")
        # Manual (SendOrder): "StopPrice — stop price, non-stop orders should
        # be -1". O valor antigo era 0.0.
        assert call["stop_price"] == -1.0
        assert call["version"] == 1  # Supported: 0, 1 — v1 sincroniza OrderType/Side

    def test_send_market_order_stop_price_minus_one(
        self, client: ProfitClient, backend: FakeProfitBackend
    ) -> None:
        with client:
            client.send_market_buy("PETR4", exchange="B", account="12345", quantity=100)
        assert _routing_call(backend, "send_order")["stop_price"] == -1.0

    def test_cancel_order_version_0(self, client: ProfitClient, backend: FakeProfitBackend) -> None:
        with client:
            client.cancel_order("12345", 1001)
        # Manual (SendCancelOrderV2): "Version — Supported: 0". O valor antigo
        # era 1 (fora do suportado; correlaciona com o travamento do cancel).
        assert _routing_call(backend, "send_cancel_order_v2")["version"] == 0

    def test_change_order_version_0(self, client: ProfitClient, backend: FakeProfitBackend) -> None:
        with client:
            client.change_order("12345", 1001, price=39.0, quantity=100)
        # Manual (SendChangeOrderV2): "Version — Supported: 0".
        assert _routing_call(backend, "send_change_order_v2")["version"] == 0

    def test_cancel_all_versions_0(self, client: ProfitClient, backend: FakeProfitBackend) -> None:
        with client:
            client.cancel_all_orders("12345", "PETR4", exchange="B")
            client.cancel_all_account_orders("12345")
        assert _routing_call(backend, "send_cancel_orders_v2")["version"] == 0
        assert _routing_call(backend, "send_cancel_all_orders")["version"] == 0

    def test_zero_position_version_1_and_market_price_minus_one(
        self, client: ProfitClient, backend: FakeProfitBackend
    ) -> None:
        with client:
            client.zero_position("PETR4", exchange="B", account="12345")
        call = _routing_call(backend, "send_zero_position_v2")
        # Manual (SendZeroPositionV2): "Version — Supported: 0 .. 1"; a partir
        # da v1 PositionType é obrigatório (sempre enviado pelo wrapper). O
        # valor antigo era 2, fora do intervalo documentado.
        assert call["version"] == 1
        assert call["price"] == -1.0  # zeramento a mercado


# --------------------------------------------------------------------------- #
# P1-4 — mapeamento de status do histórico de ordens
# --------------------------------------------------------------------------- #
def _history_order(local_id: int, status: int) -> TConnectorOrder:
    order = TConnectorOrder()
    order.Version = 0
    order.OrderID.LocalOrderID = local_id
    order.OrderID.ClOrderID = ""
    order.AccountID.AccountID = "12345"
    order.AssetID.Ticker = "PETR4"
    order.AssetID.Exchange = "B"
    order.OrderSide = 1  # Buy
    order.OrderType = 2  # Limit
    order.OrderStatus = status
    order.Quantity = 100
    order.TradedQuantity = 0
    order.LeavesQuantity = 100
    order.Price = 38.5
    order.AveragePrice = 0.0
    order.TextMessage = ""
    return order


class TestOrderHistoryStatusMapping:
    @pytest.mark.parametrize(
        ("raw_status", "expected"),
        [
            (1, OrderStatus.PARTIALLY_FILLED),
            (2, OrderStatus.FILLED),
            (4, OrderStatus.CANCELED),
            (8, OrderStatus.REJECTED),
        ],
    )
    def test_status_maps_to_order_status_enum(
        self,
        client: ProfitClient,
        backend: FakeProfitBackend,
        raw_status: int,
        expected: OrderStatus,
    ) -> None:
        """O mapa ad-hoc antigo mapeava 1=FILLED, 2=CANCELED, 3=REJECTED,
        4=PARTIALLY_FILLED — contradizendo TConnectorOrderStatus e o próprio
        OrderStatus do wrapper."""
        backend.mock_history_orders = [_history_order(1, raw_status)]
        with client:
            orders = client.get_order_history("12345")
        assert len(orders) == 1
        assert orders[0].status == expected

    def test_unknown_status_degrades_to_unknown(
        self, client: ProfitClient, backend: FakeProfitBackend
    ) -> None:
        backend.mock_history_orders = [_history_order(1, 199)]
        with client:
            orders = client.get_order_history("12345")
        assert orders[0].status == OrderStatus.UNKNOWN


# --------------------------------------------------------------------------- #
# Códigos mrc (TConnectorTradingMessageResultCode)
# --------------------------------------------------------------------------- #
class TestTradingMessageResultCode:
    def test_acceptance_chain(self) -> None:
        """Cadeia de aceite saudável documentada no manual: 2 -> 4 -> 6 -> 8 -> 10."""
        assert int(TradingMessageResultCode.SENT_TO_HADES_PROXY) == 2
        assert int(TradingMessageResultCode.SENT_TO_HADES) == 4
        assert int(TradingMessageResultCode.SENT_TO_BROKER) == 6
        assert int(TradingMessageResultCode.SENT_TO_MARKET) == 8
        assert int(TradingMessageResultCode.ACCEPTED) == 10

    def test_rejection_codes(self) -> None:
        assert int(TradingMessageResultCode.REJECTED_MERCURY) == 3
        assert int(TradingMessageResultCode.REJECTED_HADES) == 5
        assert int(TradingMessageResultCode.REJECTED_BROKER) == 7
        assert int(TradingMessageResultCode.REJECTED_MARKET) == 9

    def test_decode_from_int(self) -> None:
        """result_code cru dos eventos TRADING_MESSAGE decai no enum."""
        assert TradingMessageResultCode(2) is TradingMessageResultCode.SENT_TO_HADES_PROXY
        with pytest.raises(ValueError):
            TradingMessageResultCode(250)
