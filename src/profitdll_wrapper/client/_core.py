"""Client core module: connection lifecycle, state management, and event handling."""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from profitdll_wrapper._bindings.enums import (
    MARKET_DATA_STATES,
    ROUTING_STATES,
    ActivationResult,
    ConnectionState,
    LoginResult,
    MarketResult,
    RoutingResult,
    SystemHealthState,
)
from profitdll_wrapper._bindings.errors import (
    AuthError,
    ProfitConnectionError,
    _check,
)
from profitdll_wrapper._bindings.functions import _unregister_active_backend
from profitdll_wrapper.client._base import _ClientBase

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger("profitdll_wrapper.client")

Mode = Literal["market_data", "routing"]

_ClientCoreT = TypeVar("_ClientCoreT", bound="_ClientCoreMixin")

# Grace period for the native ConnectorThread to unwind after DLLFinalize
# before the dispatcher stops (seconds).
_TEARDOWN_GRACE_SECONDS = 0.25

_STATES_BY_MODE: dict[str, frozenset[ConnectionState]] = {
    "market_data": MARKET_DATA_STATES,
    "routing": ROUTING_STATES,
}

# Human-readable names for n_result values, keyed by connection domain.
# Used to enrich timeout diagnostics with the last observed result per domain.
_RESULT_NAME_BY_STATE: dict[ConnectionState, dict[int, str]] = {
    ConnectionState.LOGIN: {int(v): v.name for v in LoginResult},
    ConnectionState.ROUTING: {int(v): v.name for v in RoutingResult},
    ConnectionState.MARKET_DATA: {int(v): v.name for v in MarketResult},
    ConnectionState.MARKET_LOGIN: {int(v): v.name for v in ActivationResult},
}

# Enum class per domain, used to build informative AuthError instances.
_RESULT_ENUM_BY_STATE: dict[ConnectionState, type] = {
    ConnectionState.LOGIN: LoginResult,
    ConnectionState.ROUTING: RoutingResult,
    ConnectionState.MARKET_DATA: MarketResult,
    ConnectionState.MARKET_LOGIN: ActivationResult,
}


class Event(str, Enum):
    """Event names observable via @client.on(...)."""

    TRADE = "TRADE"
    PRICE_LEVEL = "PRICE_LEVEL"
    PRICE_SNAPSHOT = "PRICE_SNAPSHOT"
    DAILY = "DAILY"
    ORDER = "ORDER"
    POSITION = "POSITION"
    ACCOUNT = "ACCOUNT"
    TRADING_MESSAGE = "TRADING_MESSAGE"
    ASSET_INFO = "ASSET_INFO"
    TICKER_STATE = "TICKER_STATE"
    HEALTH_CHANGE = "HEALTH_CHANGE"
    HISTORICAL_TRADE = "HISTORICAL_TRADE"
    ADJUST_HISTORY = "ADJUST_HISTORY"
    INVALID_TICKER = "INVALID_TICKER"
    ERROR = "ERROR"
    STATE = "STATE"


class _ClientCoreMixin(_ClientBase):
    """Mixin containing connection lifecycle and event setup methods."""

    @property
    def is_connected(self) -> bool:
        """True after connect() completes successfully."""
        return self._is_connected

    def _resolve_broker_id(self, broker_id: int | None, *, account: str | None = None) -> int:
        """Resolves the broker ID to use for an account-scoped DLL call.

        Precedence: explicit argument, then the client-level default (constructor
        argument or ``BROKER`` in the ``.env``), then a lookup of the account in
        the broker's account list. Raises ValueError when nothing resolves.
        """
        if broker_id is not None:
            return int(broker_id)
        default = self._broker_id
        if default is not None:
            return int(default)
        if account:
            for acc in self.get_accounts(include_subaccounts=False):
                if acc.account_id == account:
                    return int(acc.broker_id)
        raise ValueError(
            "broker_id could not be resolved: pass broker_id explicitly, set it in the "
            "ProfitClient(broker_id=...) constructor, or define BROKER in the .env file."
        )

    def _is_state_set(self, state: ConnectionState) -> bool:
        evt = self._state_events.get(state)
        return evt is not None and evt.is_set()

    def connect(self, *, timeout: float = 30.0) -> None:
        """Initializes DLL native connection and waits for authentication.

        If connection setup fails after the native DLL has spawned its
        ConnectorThread, the DLL is finalized cleanly (``DLLFinalize``) so the
        native thread does not outlive the client and crash the interpreter on
        shutdown. The original exception is re-raised after teardown.
        """
        if self._is_connected:
            return

        self._tearing_down = False
        self._order_history_loaded = threading.Event()
        self._login_error = None
        self._login_error_state_val = None
        expected = _STATES_BY_MODE[self._mode]
        self._state_events = {state: threading.Event() for state in expected}
        self._last_state_results = {}

        try:
            if self._mode == "routing":
                code = self._backend.initialize_login(
                    self._activation_key,
                    self._user,
                    self._password,
                    self._state_cb,
                    self._daily_cb,
                    self._order_change_v2_cb,
                )
            else:
                code = self._backend.initialize_market_login(
                    self._activation_key,
                    self._user,
                    self._password,
                    self._state_cb,
                    self._daily_cb,
                )
            _check(code)

            cb_funcs: list[tuple[str, Callable[[], int]]] = [
                (
                    "set_trade_callback_v2",
                    lambda: self._backend.set_trade_callback_v2(self._trade_cb),
                ),
                (
                    "set_price_depth_callback",
                    lambda: self._backend.set_price_depth_callback(self._price_depth_cb),
                ),
                (
                    "set_offer_book_callback_v2",
                    lambda: self._backend.set_offer_book_callback_v2(self._offer_book_v2_cb),
                ),
                ("set_order_callback", lambda: self._backend.set_order_callback(self._order_cb)),
                (
                    "set_order_history_callback",
                    lambda: self._backend.set_order_history_callback(self._order_history_cb),
                ),
                (
                    "set_asset_position_list_callback",
                    lambda: self._backend.set_asset_position_list_callback(self._position_list_cb),
                ),
                (
                    "set_trading_message_result_callback",
                    lambda: self._backend.set_trading_message_result_callback(
                        self._trading_message_cb
                    ),
                ),
                (
                    "set_asset_list_info_callback_v2",
                    lambda: self._backend.set_asset_list_info_callback_v2(
                        self._asset_list_info_v2_cb
                    ),
                ),
                (
                    "set_change_state_ticker_callback",
                    lambda: self._backend.set_change_state_ticker_callback(
                        self._change_state_ticker_cb
                    ),
                ),
                (
                    "set_health_callback",
                    lambda: self._backend.set_health_callback(self._health_cb),
                ),
                (
                    "set_history_trade_callback_v2",
                    lambda: self._backend.set_history_trade_callback_v2(self._history_trade_cb),
                ),
                (
                    "set_adjust_history_callback_v2",
                    lambda: self._backend.set_adjust_history_callback_v2(
                        self._adjust_history_v2_cb
                    ),
                ),
                (
                    "set_invalid_ticker_callback",
                    lambda: self._backend.set_invalid_ticker_callback(self._invalid_ticker_cb),
                ),
            ]
            for name, fn in cb_funcs:
                try:
                    res = fn()
                    if res != 0:
                        logger.warning("Callback %s returned code %s", name, res)
                except Exception as exc:
                    logger.warning("Failed to register callback %s: %s", name, exc)

            self._dispatcher.start()
            self._wait_for_states(expected, timeout=timeout)
        except BaseException:
            # Ensure DLLFinalize runs even if connect() raises (timeout/auth/
            # exception), so the native ConnectorThread is torn down and the
            # interpreter does not crash with an access violation on shutdown.
            self._disconnect_safely()
            raise

        self._is_connected = True
        self._has_connected_once = True

    def _wait_for_states(self, expected: frozenset[ConnectionState], *, timeout: float) -> None:
        """Blocks until all expected connection states reach OK or timeout/error."""
        deadline = time.monotonic() + timeout
        poll = 0.05
        remaining: set[ConnectionState] = set(expected)
        while remaining:
            if self._login_error is not None:
                raise self._auth_error_from_code(self._login_error)
            now = time.monotonic()
            if now >= deadline:
                still = ", ".join(
                    f"{s.name} (last seen: {self._format_state_result(s)})"
                    for s in sorted(remaining)
                )
                raise ProfitConnectionError(f"Connection wait timeout. Pending domains: {still}.")
            wait_for = min(poll, deadline - now)
            any_evt = self._state_events[next(iter(remaining))]
            any_evt.wait(timeout=wait_for)
            remaining = {s for s in remaining if not self._is_state_set(s)}

        if self._login_error is not None:
            raise self._auth_error_from_code(self._login_error)

    def _auth_error_from_code(self, code: int) -> AuthError:
        """Builds an AuthError with a best-effort enum for the login failure code.

        Enriches the message with the failing domain and its result name when
        available (e.g. ``ROUTING returned BROKER_DISCONNECTED``).
        """
        from profitdll_wrapper._bindings.errors import NLCode

        state = self._login_error_state
        result_map = _RESULT_NAME_BY_STATE.get(state, {}) if state is not None else {}
        result_name = result_map.get(code)
        err_code: Any
        try:
            if state is not None:
                enum_cls = _RESULT_ENUM_BY_STATE.get(state)
                err_code = enum_cls(code) if enum_cls is not None else code
            else:
                err_code = LoginResult(code)
        except ValueError:
            err_code = NLCode.INTERNAL_ERROR
        err = AuthError(err_code)
        if state is not None and result_name is not None:
            err.args = (f"{state.name} returned {result_name} ({code})",)
        elif state is not None:
            err.args = (f"{state.name} returned result code {code}",)
        return err

    def _format_state_result(self, state: ConnectionState) -> str:
        """Human-readable label of the last n_result received for a domain."""
        raw = self._last_state_results.get(state)
        if raw is None:
            return "none"
        name = _RESULT_NAME_BY_STATE.get(state, {}).get(raw)
        return f"{name}={raw}" if name else str(raw)

    def set_enabled_hist_order(self, enabled: bool) -> None:
        """Enables or disables automatic historical order loading on startup."""
        code = self._backend.set_enabled_hist_order(1 if enabled else 0)
        _check(code)

    def get_health_status(self) -> SystemHealthState:
        """Queries thread health status watchdog of native DLL (v4.0.0.41)."""
        out_state = ctypes.c_int()
        code = self._backend.get_health_status(ctypes.byref(out_state))
        _check(code)
        try:
            return SystemHealthState(out_state.value)
        except ValueError:
            return SystemHealthState.FROZEN

    def disconnect(self) -> None:
        """Cleanly shuts down DLL services and event dispatcher daemon.

        Idempotent and never raises: safe to call from ``__exit__`` and from
        the ``connect()`` failure path. This guarantees the native
        ConnectorThread is torn down via ``DLLFinalize`` even when connection
        setup fails partway, preventing access-violation crashes on
        interpreter shutdown.
        """
        self._disconnect_safely()

    def _disconnect_safely(self) -> None:
        """Idempotent teardown core: unregisters callbacks, finalizes the native
        DLL, then stops the dispatcher. Logs failures instead of raising.

        Ordering rationale: the native DLL owns a background "ConnectorThread"
        that invokes the registered C callbacks. We unregister callbacks first
        (so the DLL stops calling back into Python), then call ``DLLFinalize``
        (which tears down that native thread), and only then stop the Python
        dispatcher. This ordering minimizes the window in which the native
        thread can fire a callback into a tearing-down interpreter, which is the
        root cause of "Windows fatal exception: access violation" on shutdown.
        """
        # Ignore state callbacks fired while tearing down (e.g. the DISCONNECTED
        # notification emitted by DLLFinalize itself) so teardown stays quiet.
        self._tearing_down = True
        try:
            try:
                self._backend.set_trade_callback_v2(None)
                self._backend.set_history_trade_callback_v2(None)
                self._backend.set_price_depth_callback(None)
                self._backend.set_offer_book_callback_v2(None)
                self._backend.set_order_change_callback_v2(None)
                self._backend.set_order_callback(None)
                self._backend.set_order_history_callback(None)
                self._backend.set_asset_position_list_callback(None)
                self._backend.set_trading_message_result_callback(None)
                self._backend.set_asset_list_info_callback_v2(None)
                self._backend.set_change_state_ticker_callback(None)
                self._backend.set_health_callback(None)
                self._backend.set_adjust_history_callback_v2(None)
                self._backend.set_invalid_ticker_callback(None)
            except Exception as e:
                logger.warning("Failed to unregister callbacks during teardown: %s", e)
            _check(self._backend.finalize())
            # Drop this backend from the atexit safety net so it is not
            # finalized twice (the explicit disconnect already did it).
            _unregister_active_backend(self._backend)
            # Give the native ConnectorThread a brief grace period to unwind
            # after DLLFinalize before continuing.
            time.sleep(_TEARDOWN_GRACE_SECONDS)
        except Exception:
            logger.exception("Error finalizing DLL")
        finally:
            self._dispatcher.stop()
            self._is_connected = False

    def on(self, event: Event | str) -> Any:
        """Decorator for registering an event handler callback."""
        name = event.value if isinstance(event, Event) else str(event)
        return self._dispatcher.on(name)

    def run(self) -> None:
        """Blocks calling thread, keeping event loop active."""
        self._dispatcher.run()

    def stop(self) -> None:
        """Signals stop event to event dispatcher."""
        self._dispatcher.stop()

    def __enter__(self: _ClientCoreT) -> _ClientCoreT:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.disconnect()
