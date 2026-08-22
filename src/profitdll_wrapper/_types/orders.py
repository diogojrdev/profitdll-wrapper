"""Data models for trading orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from profitdll_wrapper._bindings.enums import OrderSide, OrderStatus, OrderType
from profitdll_wrapper._types.core import AssetId


@dataclass(frozen=True, slots=True)
class Order:
    """Trading order representation (real-time order routing event).

    Attributes:
        id: ProfitID or LocalOrderID identifier.
        cl_ord_id: Client order ID.
        asset: Target asset identifier.
        side: Order side (BUY, SELL).
        order_type: Order type (MARKET, LIMIT, STOP, STOP_LIMIT).
        status: Execution order status.
        price: Limit price.
        quantity: Total order quantity.
        traded_quantity: Executed quantity.
        leaves_quantity: Remaining quantity.
        average_price: Execution average price.
        account_id: Trading account ID.
        timestamp: Last update timestamp.
        text_message: Status or rejection message from exchange/broker.
    """

    id: int
    cl_ord_id: str
    asset: AssetId
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    price: float
    quantity: int
    traded_quantity: int
    leaves_quantity: int
    average_price: float
    account_id: str
    timestamp: datetime
    text_message: str = ""


__all__ = ["Order"]
