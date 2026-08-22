"""ProfitClient facade class composing client mixins."""

from __future__ import annotations

import logging
import threading

from profitdll_wrapper._bindings.callbacks import (
    TAdjustHistoryCallbackV2,
    TAssetListInfoCallbackV2,
    TAssetPositionListCallback,
    TChangeStateTicker,
    TConnectorAccountCallback,
    TConnectorOrderCallback,
    TConnectorTradingMessageResultCallback,
    TDailyCallback,
    TInvalidTickerCallback,
    TOfferBookCallbackV2,
    TOrderChangeCallbackV2,
    TPriceDepthCallback,
    TStateCallback,
    TSystemHealthCallback,
    TTradeCallbackV2,
    keep_alive,
)
from profitdll_wrapper._bindings.enums import ConnectionState
from profitdll_wrapper._bindings.functions import Backend, get_backend
from profitdll_wrapper._events.dispatcher import EventDispatcher
from profitdll_wrapper.client._accounts import _ClientAccountsMixin
from profitdll_wrapper.client._callback_handlers import _ClientCallbackMixin
from profitdll_wrapper.client._core import _STATES_BY_MODE, Mode, _ClientCoreMixin
from profitdll_wrapper.client._market_data import _ClientMarketDataMixin
from profitdll_wrapper.client._routing import _ClientRoutingMixin

logger = logging.getLogger("profitdll_wrapper.client")


def _broker_from_env() -> int | None:
    """Reads the default broker ID from the environment / .env (``BROKER``)."""
    from profitdll_wrapper._config import load_credentials

    raw = load_credentials().get("broker", "")
    try:
        return int(raw) if raw else None
    except ValueError:
        logger.warning("Ignoring non-numeric BROKER value in .env: %r", raw)
        return None


class ProfitClient(
    _ClientCoreMixin,
    _ClientCallbackMixin,
    _ClientMarketDataMixin,
    _ClientRoutingMixin,
    _ClientAccountsMixin,
):
    """High-level ProfitDLL client facade.

    Args:
        activation_key: Account activation key string.
        user: User username / email.
        password: User password.
        mode: Operating mode ("market_data" or "routing"). Default: "market_data".
        backend: Injectable Backend instance (for testing). Defaults to native loader.
        auto_resubscribe: Automatically re-establishes active market data subscriptions on reconnect.
        broker_id: Default broker ID for account-scoped calls (orders, positions,
            order history). When omitted, it is read from the ``BROKER`` entry of
            the ``.env`` file; if that is also absent, each call resolves it from
            the broker's account list or raises ValueError.
    """

    def __init__(
        self,
        *,
        activation_key: str,
        user: str,
        password: str,
        mode: Mode = "market_data",
        backend: Backend | None = None,
        auto_resubscribe: bool = True,
        broker_id: int | None = None,
    ) -> None:
        if mode not in _STATES_BY_MODE:
            raise ValueError(f"mode must be 'market_data' or 'routing', got: {mode!r}")
        self._mode: Mode = mode
        self._backend: Backend = backend if backend is not None else get_backend()
        self._dispatcher = EventDispatcher(self._backend)

        self._activation_key = activation_key
        self._user = user
        self._password = password
        self._auto_resubscribe = auto_resubscribe
        self._broker_id = broker_id if broker_id is not None else _broker_from_env()

        self._is_connected = False
        self._tearing_down = False
        self._order_history_loaded = threading.Event()
        self._has_connected_once = False
        self._state_events = {}
        self._last_state_results: dict[ConnectionState, int] = {}
        self._login_error_lock = threading.Lock()
        self._login_error_val = None
        self._login_error_state_val = None

        self._subscriptions_lock = threading.Lock()
        self._active_subscriptions: set[tuple[str, str, str]] = set()

        self._state_cb = keep_alive("state", TStateCallback(self._on_state))
        self._trade_cb = keep_alive("trade", TTradeCallbackV2(self._on_trade))
        self._price_depth_cb = keep_alive("price_depth", TPriceDepthCallback(self._on_price_depth))
        self._offer_book_v2_cb = keep_alive(
            "offer_book_v2", TOfferBookCallbackV2(self._on_offer_book_v2)
        )
        self._daily_cb = keep_alive("daily", TDailyCallback(self._on_daily))
        self._order_change_v2_cb = keep_alive(
            "order_change_v2", TOrderChangeCallbackV2(self._on_order_change_v2)
        )
        self._order_cb = keep_alive("order", TConnectorOrderCallback(self._on_order_callback))
        self._order_history_cb = keep_alive(
            "order_history", TConnectorAccountCallback(self._on_order_history_loaded)
        )
        self._position_list_cb = keep_alive(
            "position_list", TAssetPositionListCallback(self._on_asset_position_list)
        )
        self._trading_message_cb = keep_alive(
            "trading_message", TConnectorTradingMessageResultCallback(self._on_trading_message)
        )
        self._asset_list_info_v2_cb = keep_alive(
            "asset_list_info_v2", TAssetListInfoCallbackV2(self._on_asset_list_info_v2)
        )
        self._change_state_ticker_cb = keep_alive(
            "change_state_ticker", TChangeStateTicker(self._on_change_state_ticker)
        )
        self._health_cb = keep_alive("health", TSystemHealthCallback(self._on_health_change))
        self._history_trade_cb = keep_alive(
            "history_trade", TTradeCallbackV2(self._on_history_trade)
        )
        self._adjust_history_v2_cb = keep_alive(
            "adjust_history_v2", TAdjustHistoryCallbackV2(self._on_adjust_history_v2)
        )
        self._invalid_ticker_cb = keep_alive(
            "invalid_ticker", TInvalidTickerCallback(self._on_invalid_ticker)
        )
