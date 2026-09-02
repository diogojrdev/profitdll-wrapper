"""Order routing, execution, modification, and cancellation mixin."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from profitdll_wrapper._bindings.enums import OrderSide, OrderType
from profitdll_wrapper._bindings.errors import NLCode
from profitdll_wrapper._bindings.structures import (
    SystemTime,
    TConnectorCancelAllOrders,
    TConnectorCancelOrder,
    TConnectorCancelOrders,
    TConnectorChangeOrder,
    TConnectorSendOrder,
    TConnectorZeroPosition,
)
from profitdll_wrapper.client._base import _ClientBase
from profitdll_wrapper.client._helpers import (
    build_account_id,
    build_asset_id,
    build_order_id,
    validate_exchange,
)

if TYPE_CHECKING:
    from profitdll_wrapper._types.orders import Order

logger = logging.getLogger("profitdll_wrapper.client")


class _ClientRoutingMixin(_ClientBase):
    """Mixin providing order routing, modification, and cancellation methods."""

    def _resolve_routing_password(self, password: str | None) -> str:
        """Resolves the routing password for an order-routing DLL call.

        The DLL validates this password on the order server (Hades) before
        forwarding anything to the broker — it is NOT the login password.
        Precedence: explicit per-call argument, then the client-level
        ``routing_password``. Raises ValueError when neither is available so a
        login password is never silently reused (invalid routing attempts can
        lock the account).
        """
        if password:
            return password
        if self._routing_password:
            return self._routing_password
        raise ValueError(
            "routing password not set: pass password= to this call or "
            "routing_password= to ProfitClient (ROUTING_KEY in .env). The routing "
            "password differs from the login password; using the wrong one makes "
            "the order server drop the order silently."
        )

    def _build_send_order(
        self,
        *,
        ticker: str,
        exchange: str,
        account: str,
        password: str | None,
        order_type: OrderType,
        order_side: OrderSide,
        price: float,
        quantity: int,
        broker_id: int | None = None,
    ) -> int:
        """Internal DRY helper for order placement via TConnectorSendOrder."""
        broker_id = self._resolve_broker_id(broker_id, account=account)
        validate_exchange(exchange)
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got: {quantity}")
        if order_type is OrderType.LIMIT and price <= 0.0:
            raise ValueError(f"price must be > 0.0, got: {price}")

        order = TConnectorSendOrder()
        order.Version = 1
        order.AccountID = build_account_id(account, broker_id)
        order.AssetID = build_asset_id(ticker, exchange)
        order.Password = self._resolve_routing_password(password)
        order.OrderType = int(order_type)
        order.OrderSide = int(order_side)
        order.Price = float(price)
        # Manual (SendOrder): "StopPrice — stop price, non-stop orders should
        # be -1". The wrapper does not expose stop order placement yet, so
        # every order sent here is non-stop.
        order.StopPrice = -1.0
        order.Quantity = int(quantity)
        order.MessageID = -1

        from ctypes import c_int64

        out_id = c_int64()
        code = self._backend.send_order(order, out_id)
        self._check_code(code)
        if out_id.value < 0:
            self._check_code(int(out_id.value))
        return int(out_id.value)

    def send_buy_order(
        self,
        ticker: str,
        *,
        exchange: str,
        account: str,
        price: float,
        quantity: int,
        password: str | None = None,
        broker_id: int | None = None,
    ) -> int:
        """Submits a limit buy order.

        Returns the **local order ID** (session-scoped identifier attributed
        by the DLL), not the permanent Profit order ID. Track acceptance via
        ``Event.TRADING_MESSAGE`` / ``Event.ORDER``.
        """
        res: int = self._build_send_order(
            ticker=ticker,
            exchange=exchange,
            account=account,
            password=password,
            order_type=OrderType.LIMIT,
            order_side=OrderSide.BUY,
            price=price,
            quantity=quantity,
            broker_id=broker_id,
        )
        return res

    def send_sell_order(
        self,
        ticker: str,
        *,
        exchange: str,
        account: str,
        price: float,
        quantity: int,
        password: str | None = None,
        broker_id: int | None = None,
    ) -> int:
        """Submits a limit sell order.

        Returns the **local order ID** (session-scoped identifier attributed
        by the DLL), not the permanent Profit order ID.
        """
        res: int = self._build_send_order(
            ticker=ticker,
            exchange=exchange,
            account=account,
            password=password,
            order_type=OrderType.LIMIT,
            order_side=OrderSide.SELL,
            price=price,
            quantity=quantity,
            broker_id=broker_id,
        )
        return res

    def send_market_buy(
        self,
        ticker: str,
        *,
        exchange: str,
        account: str,
        quantity: int,
        password: str | None = None,
        broker_id: int | None = None,
    ) -> int:
        """Submits a market buy order.

        Returns the **local order ID** (session-scoped identifier attributed
        by the DLL), not the permanent Profit order ID.
        """
        res: int = self._build_send_order(
            ticker=ticker,
            exchange=exchange,
            account=account,
            password=password,
            order_type=OrderType.MARKET,
            order_side=OrderSide.BUY,
            price=0.0,
            quantity=quantity,
            broker_id=broker_id,
        )
        return res

    def send_market_sell(
        self,
        ticker: str,
        *,
        exchange: str,
        account: str,
        quantity: int,
        password: str | None = None,
        broker_id: int | None = None,
    ) -> int:
        """Submits a market sell order.

        Returns the **local order ID** (session-scoped identifier attributed
        by the DLL), not the permanent Profit order ID.
        """
        res: int = self._build_send_order(
            ticker=ticker,
            exchange=exchange,
            account=account,
            password=password,
            order_type=OrderType.MARKET,
            order_side=OrderSide.SELL,
            price=0.0,
            quantity=quantity,
            broker_id=broker_id,
        )
        return res

    def cancel_order(
        self,
        account: str,
        order_id: int,
        *,
        password: str | None = None,
        cl_ord_id: str = "",
        broker_id: int | None = None,
    ) -> None:
        """Cancels an active order by ID."""
        broker_id = self._resolve_broker_id(broker_id, account=account)
        cancel = TConnectorCancelOrder()
        # Manual (SendCancelOrderV2): "Version — Supported: 0".
        cancel.Version = 0
        cancel.AccountID = build_account_id(account, broker_id)
        cancel.OrderID = build_order_id(order_id, cl_ord_id)
        cancel.Password = self._resolve_routing_password(password)
        cancel.MessageID = -1

        code = self._backend.send_cancel_order_v2(cancel)
        self._check_code(code)

    def change_order(
        self,
        account: str,
        order_id: int,
        price: float,
        quantity: int,
        *,
        password: str | None = None,
        stop_price: float = 0.0,
        cl_ord_id: str = "",
        broker_id: int | None = None,
    ) -> None:
        """Modifies price or quantity of an active limit or stop order."""
        broker_id = self._resolve_broker_id(broker_id, account=account)
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got: {quantity}")
        if price < 0.0:
            raise ValueError(f"price cannot be negative, got: {price}")
        if stop_price < 0.0:
            raise ValueError(f"stop_price cannot be negative, got: {stop_price}")

        change = TConnectorChangeOrder()
        # Manual (SendChangeOrderV2): "Version — Supported: 0".
        change.Version = 0
        change.AccountID = build_account_id(account, broker_id)
        change.OrderID = build_order_id(order_id, cl_ord_id)
        change.Password = self._resolve_routing_password(password)
        change.Price = float(price)
        change.StopPrice = float(stop_price)
        change.Quantity = int(quantity)
        change.MessageID = -1

        code = self._backend.send_change_order_v2(change)
        self._check_code(code)

    def cancel_all_orders(
        self,
        account: str,
        ticker: str,
        *,
        exchange: str,
        password: str | None = None,
        broker_id: int | None = None,
    ) -> None:
        """Cancels all active orders for a specific asset."""
        broker_id = self._resolve_broker_id(broker_id, account=account)
        validate_exchange(exchange)
        cancel = TConnectorCancelOrders()
        cancel.Version = 0
        cancel.AccountID = build_account_id(account, broker_id)
        cancel.AssetID = build_asset_id(ticker, exchange)
        cancel.Password = self._resolve_routing_password(password)

        code = self._backend.send_cancel_orders_v2(cancel)
        self._check_code(code)

    def cancel_all_account_orders(
        self,
        account: str,
        *,
        password: str | None = None,
        broker_id: int | None = None,
    ) -> None:
        """Cancels all active orders across all assets for an account."""
        broker_id = self._resolve_broker_id(broker_id, account=account)
        cancel = TConnectorCancelAllOrders()
        cancel.Version = 0
        cancel.AccountID = build_account_id(account, broker_id)
        cancel.Password = self._resolve_routing_password(password)

        code = self._backend.send_cancel_all_orders(cancel)
        self._check_code(code)

    def zero_position(
        self,
        ticker: str,
        *,
        exchange: str,
        account: str,
        password: str | None = None,
        price: float = -1.0,
        position_type: int = 0,
        broker_id: int | None = None,
    ) -> int:
        """Submits a zero position order for an asset.

        Returns the **local order ID** (session-scoped identifier attributed
        by the DLL), not the permanent Profit order ID.
        """
        broker_id = self._resolve_broker_id(broker_id, account=account)
        validate_exchange(exchange)
        zero = TConnectorZeroPosition()
        # Manual (SendZeroPositionV2): "Version — Supported: 0 .. 1"; from
        # version 1 onwards PositionType is required (always sent here).
        zero.Version = 1
        zero.AccountID = build_account_id(account, broker_id)
        zero.AssetID = build_asset_id(ticker, exchange)
        zero.Password = self._resolve_routing_password(password)
        zero.Price = float(price)
        zero.PositionType = int(position_type)
        zero.MessageID = -1

        from ctypes import c_int64

        out_id = c_int64()
        code = self._backend.send_zero_position_v2(zero, out_id)
        self._check_code(code)
        if out_id.value < 0:
            self._check_code(int(out_id.value))
        return int(out_id.value)

    def get_order_history(
        self,
        account: str,
        *,
        start_date: str = "",
        end_date: str = "",
        broker_id: int | None = None,
        wait_timeout: float = 10.0,
    ) -> list[Order]:
        """Queries and reconciles account order history.

        When filtering by interval, the DLL may answer ``NL_WAITING_SERVER``
        while the historical orders are still downloading; the query is retried
        until ``wait_timeout`` seconds elapse. An ``NL_OUT_OF_RANGE`` answer
        means there are no orders in the interval and an empty list is
        returned.
        """
        import time as _time

        broker_id = self._resolve_broker_id(broker_id, account=account)
        from datetime import datetime

        from profitdll_wrapper._bindings.callbacks import TConnectorEnumerateOrdersProc
        from profitdll_wrapper._bindings.enums import OrderSide, OrderStatus, OrderType
        from profitdll_wrapper._types.core import AssetId
        from profitdll_wrapper._types.orders import Order

        orders: list[Order] = []

        def enum_cb(p_order: Any, param: int) -> bool:
            if not p_order:
                return True
            ord_struct = p_order.contents if hasattr(p_order, "contents") else p_order
            if not ord_struct:
                return True

            ticker = str(ord_struct.AssetID.Ticker or "").strip()
            exchange = str(ord_struct.AssetID.Exchange or "").strip()
            asset_id = AssetId(ticker=ticker, exchange=exchange)
            side_e = OrderSide.BUY if ord_struct.OrderSide == 1 else OrderSide.SELL

            otype_map = {1: OrderType.MARKET, 2: OrderType.LIMIT, 4: OrderType.STOP}
            order_type_e = otype_map.get(ord_struct.OrderType, OrderType.LIMIT)

            # TConnectorOrderStatus maps 1:1 onto the OrderStatus enum
            # (1=PartiallyFilled, 2=Filled, 4=Canceled, 8=Rejected, ...);
            # unknown codes degrade to UNKNOWN instead of a wrong status.
            try:
                status_e = OrderStatus(ord_struct.OrderStatus)
            except ValueError:
                status_e = OrderStatus.UNKNOWN

            profit_id = int(ord_struct.OrderID.LocalOrderID or 0)
            cl_ord_id = str(ord_struct.OrderID.ClOrderID or "")
            account_id = str(ord_struct.AccountID.AccountID or account)
            text_msg = str(ord_struct.TextMessage or "").strip()

            orders.append(
                Order(
                    id=profit_id,
                    cl_ord_id=cl_ord_id,
                    asset=asset_id,
                    side=side_e,
                    order_type=order_type_e,
                    status=status_e,
                    price=float(ord_struct.Price),
                    quantity=int(ord_struct.Quantity),
                    traded_quantity=int(ord_struct.TradedQuantity),
                    leaves_quantity=int(ord_struct.LeavesQuantity),
                    average_price=float(ord_struct.AveragePrice),
                    account_id=account_id,
                    timestamp=datetime.now(),
                    text_message=text_msg,
                )
            )
            return True

        acc_id = build_account_id(account, broker_id)
        cb_proc = TConnectorEnumerateOrdersProc(enum_cb)

        if start_date and end_date:
            # The interval history downloads asynchronously after connect
            # (SetOrderHistoryCallback is registered on connect and sets
            # _order_history_loaded when done). Polling the DLL too eagerly
            # restarts the download, so wait on the event between attempts.
            deadline = _time.monotonic() + max(wait_timeout, 0.0)
            t_start = _time.monotonic()
            evt = getattr(self, "_order_history_loaded", None)
            # The DLL reports NL codes as signed 32-bit ints (e.g. -2147483644
            # for NL_WAITING_SERVER); normalize before comparing with NLCode.
            waiting = int(NLCode.WAITING_SERVER) & 0xFFFFFFFF
            out_of_range = int(NLCode.OUT_OF_RANGE) & 0xFFFFFFFF
            while True:
                code = self._backend.enumerate_orders_by_interval(
                    acc_id,
                    1,
                    _parse_system_time(start_date),
                    _parse_system_time(end_date),
                    0,
                    cb_proc,
                )
                logger.debug(
                    "EnumerateOrdersByInterval returned %#x after %.1fs",
                    code & 0xFFFFFFFF,
                    _time.monotonic() - t_start,
                )
                if (code & 0xFFFFFFFF) != waiting or _time.monotonic() >= deadline:
                    break
                if evt is not None:
                    evt.wait(timeout=min(2.0, deadline - _time.monotonic()))
                    evt.clear()
                else:
                    _time.sleep(2.0)
            if (code & 0xFFFFFFFF) == out_of_range:
                # No orders exist in the requested interval.
                return orders
        else:
            code = self._backend.enumerate_all_orders(acc_id, 1, 0, cb_proc)

        self._check_code(code)
        return orders


def _parse_system_time(date_str: str) -> SystemTime:
    """Parses a date string into the TSystemTime struct the DLL expects.

    Accepted formats: ``DD/MM/YYYY``, ``DD/MM/YYYY HH:MM[:SS]`` and ISO
    ``YYYY-MM-DD[ HH:MM[:SS]]``.
    """
    from datetime import datetime

    normalized = date_str.strip()
    formats = (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(normalized, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(
            f"Invalid date {date_str!r}: expected 'DD/MM/YYYY', 'DD/MM/YYYY HH:MM[:SS]' "
            "or ISO 'YYYY-MM-DD'."
        )

    st = SystemTime()
    st.wYear = dt.year
    st.wMonth = dt.month
    st.wDay = dt.day
    st.wHour = dt.hour
    st.wMinute = dt.minute
    st.wSecond = dt.second
    st.wMilliseconds = 0
    return st
