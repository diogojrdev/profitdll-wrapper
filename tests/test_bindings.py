"""Testes da camada de bindings: erros NL_*, enums e keep-alive."""

from __future__ import annotations

import pytest

from profitdll_wrapper._bindings.callbacks import keep_alive
from profitdll_wrapper._bindings.enums import (
    OK_RESULT_BY_STATE,
    BookSide,
    BookUpdateType,
    ConnectionState,
    ExchangeCode,
    LoginResult,
    MarketResult,
    RoutingResult,
)
from profitdll_wrapper._bindings.errors import (
    AuthError,
    InvalidArgumentError,
    NLCode,
    ProfitAPIError,
    ServerStateError,
    _check,
)
from profitdll_wrapper._bindings.structures import (
    PG_IS_THEORIC,
    TAssetID,
    TConnectorPriceGroup,
)


class TestNLCode:
    def test_ok_is_zero(self) -> None:
        assert int(NLCode.OK) == 0

    def test_error_codes_have_high_bit_set(self) -> None:
        for code in (NLCode.INTERNAL_ERROR, NLCode.NO_LOGIN, NLCode.INVALID_TICKER):
            assert int(code) & 0x80000000 != 0

    def test_invalid_ticker_value_matches_documented_code(self) -> None:
        # 0x8000001F (código oficial documentado).
        assert int(NLCode.INVALID_TICKER) == 0x8000001F


class TestCheck:
    def test_ok_does_not_raise(self) -> None:
        _check(0)  # NL_OK

    def test_no_login_raises_auth_error(self) -> None:
        with pytest.raises(AuthError) as exc_info:
            _check(int(NLCode.NO_LOGIN))
        assert exc_info.value.code is NLCode.NO_LOGIN

    def test_no_license_raises_auth_error(self) -> None:
        with pytest.raises(AuthError):
            _check(int(NLCode.NO_LICENSE))

    def test_invalid_args_raises_invalid_argument(self) -> None:
        with pytest.raises(InvalidArgumentError):
            _check(int(NLCode.INVALID_ARGS))

    def test_invalid_ticker_raises_invalid_argument(self) -> None:
        with pytest.raises(InvalidArgumentError):
            _check(int(NLCode.INVALID_TICKER))

    def test_waiting_server_raises_server_state(self) -> None:
        with pytest.raises(ServerStateError):
            _check(int(NLCode.WAITING_SERVER))

    def test_generic_error_falls_back_to_profit_api_error(self) -> None:
        with pytest.raises(ProfitAPIError):
            _check(int(NLCode.INTERNAL_ERROR))


class TestConnectionStateEnums:
    def test_connection_state_values(self) -> None:
        assert int(ConnectionState.LOGIN) == 0
        assert int(ConnectionState.MARKET_DATA) == 2
        assert int(ConnectionState.MARKET_LOGIN) == 3

    def test_login_connected_is_zero(self) -> None:
        assert int(LoginResult.CONNECTED) == 0

    def test_market_connected_is_four(self) -> None:
        assert int(MarketResult.CONNECTED) == 4

    def test_ok_result_by_state_mapping(self) -> None:
        assert OK_RESULT_BY_STATE[ConnectionState.LOGIN] == int(LoginResult.CONNECTED)
        assert OK_RESULT_BY_STATE[ConnectionState.MARKET_DATA] == int(MarketResult.CONNECTED)
        assert OK_RESULT_BY_STATE[ConnectionState.ROUTING] == int(RoutingResult.BROKER_CONNECTED)


class TestExchangeCode:
    @pytest.mark.parametrize(
        ("value", "name"),
        [
            ("B", "BOVESPA"),
            ("F", "BMF"),
            ("D", "CAMBIO"),
        ],
    )
    def test_known_exchanges(self, value: str, name: str) -> None:
        assert ExchangeCode(value).name == name

    def test_unknown_exchange_raises(self) -> None:
        with pytest.raises(ValueError):
            ExchangeCode("Z")


class TestKeepAlive:
    def test_keep_alive_retains_reference(self) -> None:
        sentinel = object()
        result = keep_alive("test-key", sentinel)
        assert result is sentinel

    def test_keep_alive_replaces(self) -> None:
        keep_alive("replace-key", object())
        new_obj = object()
        keep_alive("replace-key", new_obj)
        # Não há exceção; a substituição é silenciosa e esperada.


class TestBookSide:
    """Valores verbatim do protocolo oficial (priceDepthCallback)."""

    def test_buy_sell_both_values(self) -> None:
        assert int(BookSide.BUY) == 0
        assert int(BookSide.SELL) == 1
        assert int(BookSide.BOTH) == 254


class TestBookUpdateType:
    """Valores verbatim do protocolo oficial (match no priceDepthCallback)."""

    def test_update_type_values(self) -> None:
        assert int(BookUpdateType.ADD) == 0
        assert int(BookUpdateType.EDIT) == 1
        assert int(BookUpdateType.DELETE) == 2
        assert int(BookUpdateType.INSERT) == 3
        assert int(BookUpdateType.FULL_BOOK) == 4
        assert int(BookUpdateType.DELETE_FROM) == 8


class TestP1Structures:
    """Layouts verbatim do protocolo oficial da DLL."""

    def test_tconnector_price_group_fields(self) -> None:
        # Campo a campo, na ordem do vendor.
        assert [f[0] for f in TConnectorPriceGroup._fields_] == [
            "Version",
            "Price",
            "Count",
            "Quantity",
            "PriceGroupFlags",
        ]

    def test_pg_is_theoric_flag(self) -> None:
        assert PG_IS_THEORIC == 1

    def test_tasset_id_fields(self) -> None:
        # Família legada (minúsculas), usada pelos callbacks de daily.
        assert [f[0] for f in TAssetID._fields_] == ["ticker", "bolsa", "feed"]
