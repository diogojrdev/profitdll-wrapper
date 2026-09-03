"""Typed attribute base shared by all ProfitClient mixins.

``ProfitClient`` composes five mixins (core, callbacks, market data, routing,
accounts) that cooperate through instance state and helpers defined on one
another. This base declares that shared surface so every mixin method is
fully checked by mypy strict — without ``self: Any`` escape hatches — while
``ProfitClient.__init__`` remains the single place that builds the state.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from profitdll_wrapper._bindings.enums import ConnectionState
    from profitdll_wrapper._bindings.functions import Backend
    from profitdll_wrapper._events.dispatcher import EventDispatcher
    from profitdll_wrapper._types.accounts import Account, Position
    from profitdll_wrapper.client._core import Mode


class _ClientBase:
    """Annotation-only declarations; every value is created by ``ProfitClient.__init__``.

    The helpers at the bottom are implemented in the mixin named in each
    docstring; the stub exists only so cross-mixin calls type-check.
    """

    # --- configuration ----------------------------------------------------
    _mode: Mode
    _backend: Backend
    _dispatcher: EventDispatcher
    _activation_key: str
    _user: str
    _password: str
    _routing_password: str
    _auto_resubscribe: bool
    _broker_id: int | None

    # --- lifecycle / connection state --------------------------------------
    _is_connected: bool
    _tearing_down: bool
    _order_history_loaded: threading.Event
    _has_connected_once: bool
    _state_events: dict[ConnectionState, threading.Event]
    _last_state_results: dict[ConnectionState, int]
    _login_error_lock: threading.Lock
    _login_error_val: int | None
    _login_error_state_val: ConnectionState | None

    # --- market data subscriptions -----------------------------------------
    _subscriptions_lock: threading.Lock
    _active_subscriptions: set[tuple[str, str, str]]

    # --- keep-alive handles for the C callbacks (built in ProfitClient.__init__) --
    # WINFUNCTYPE products are not valid static type expressions; "object"
    # matches the Backend protocol's own callback parameter type.
    _state_cb: object
    _trade_cb: object
    _price_depth_cb: object
    _offer_book_v2_cb: object
    _daily_cb: object
    _order_change_v2_cb: object
    _order_cb: object
    _order_history_cb: object
    _position_list_cb: object
    _trading_message_cb: object
    _asset_list_info_v2_cb: object
    _change_state_ticker_cb: object
    _health_cb: object
    _history_trade_cb: object
    _progress_cb: object
    _adjust_history_v2_cb: object
    _invalid_ticker_cb: object

    # --- cross-mixin state helpers ------------------------------------------
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
        """Records a terminal login failure (domain + result) atomically.

        Only the first failure is kept so the user sees the root cause rather
        than a later, secondary state change.
        """
        with self._login_error_lock:
            if self._login_error_val is None:
                self._login_error_val = n_result
                self._login_error_state_val = state

    def _record_state_result(self, state: ConnectionState, n_result: int) -> None:
        """Tracks the last n_result per domain for timeout diagnostics."""
        self._last_state_results[state] = n_result

    def _check_code(self, code: int) -> None:
        """Validates an API return code, raising the mapped ProfitError."""
        from profitdll_wrapper._bindings.errors import _check

        _check(code)

    # --- implemented in _ClientCoreMixin -------------------------------------
    def _resolve_broker_id(self, broker_id: int | None, *, account: str | None = None) -> int:
        """Implemented in ``_ClientCoreMixin``."""
        raise NotImplementedError

    # --- implemented in _ClientMarketDataMixin --------------------------------
    def resubscribe_all(self) -> int:
        """Implemented in ``_ClientMarketDataMixin``."""
        raise NotImplementedError

    # --- implemented in _ClientAccountsMixin ---------------------------------
    def get_accounts(self, include_subaccounts: bool = True) -> list[Account]:
        """Implemented in ``_ClientAccountsMixin``."""
        raise NotImplementedError

    def get_position(
        self,
        ticker: str,
        *,
        exchange: str,
        account: str,
        broker_id: int | None = None,
    ) -> Position:
        """Implemented in ``_ClientAccountsMixin``."""
        raise NotImplementedError
