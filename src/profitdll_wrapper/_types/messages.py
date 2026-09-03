"""Data models for trading messages, asset specifications, candles, and corporate actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from profitdll_wrapper._bindings.enums import TickerState
from profitdll_wrapper._types.core import AssetId


@dataclass(frozen=True, slots=True)
class DailyCandle:
    """Daily candle summary event.

    Attributes:
        asset: Target asset identifier.
        date: Date string ("DD/MM/YYYY HH:mm:SS.ZZZ").
        open: Opening price.
        high: High price.
        low: Low price.
        close: Closing price.
        volume: Financial volume.
        adjustment: Adjustment price (derivatives).
        max_limit: Upper price limit.
        min_limit: Lower price limit.
        volume_buyer: Buying volume.
        volume_seller: Selling volume.
        quantity: Total contract quantity.
        trades: Total trade count.
        open_interest: Open interest count.
        quantity_buyer: Buyer contract quantity.
        quantity_seller: Seller contract quantity.
        trades_buyer: Buyer trade count.
        trades_seller: Seller trade count.
    """

    asset: AssetId
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjustment: float
    max_limit: float
    min_limit: float
    volume_buyer: float
    volume_seller: float
    quantity: int
    trades: int
    open_interest: int
    quantity_buyer: int
    quantity_seller: int
    trades_buyer: int
    trades_seller: int


@dataclass(frozen=True, slots=True)
class TradingMessageResult:
    """Trading message/risk notification emitted by server.

    Attributes:
        broker_id: Broker ID.
        local_order_id: Local order ID.
        cl_ord_id: Client order ID.
        message_id: Unique message ID.
        result_code: Result status code.
        message: Explanatory text message.
    """

    broker_id: int
    local_order_id: int
    cl_ord_id: str
    message_id: int
    result_code: int
    message: str

    @classmethod
    def from_native(cls, res: Any) -> TradingMessageResult:
        """Constructs from native TConnectorTradingMessageResult structure."""
        return cls(
            broker_id=int(res.BrokerID),
            local_order_id=int(res.OrderID.LocalOrderID),
            cl_ord_id=str(res.OrderID.ClOrderID or "").strip(),
            message_id=int(res.MessageID),
            result_code=int(res.ResultCode),
            message=str(res.Message or "").strip(),
        )


@dataclass(frozen=True, slots=True)
class AssetInfo:
    """Detailed asset specification and trading rules.

    Attributes:
        asset: Asset identifier.
        name: Asset name.
        description: Detailed asset description.
        min_order_qty: Minimum order quantity.
        max_order_qty: Maximum order quantity.
        lot_size: Standard round lot size.
        security_type: Security type code.
        security_subtype: Security subtype code.
        min_price_increment: Tick size increment.
        contract_multiplier: Contract multiplier.
        valid_date: Expiration date.
        isin: ISIN code.
        sector: Market sector.
        subsector: Market subsector.
        segment: Market segment.
    """

    asset: AssetId
    name: str
    description: str
    min_order_qty: int
    max_order_qty: int
    lot_size: int
    security_type: int
    security_subtype: int
    min_price_increment: float
    contract_multiplier: float
    valid_date: str
    isin: str
    sector: str
    subsector: str
    segment: str


@dataclass(frozen=True, slots=True)
class TickerStateChange:
    """Trading state change event (e.g. Opened, Auction, Closed).

    Attributes:
        asset: Asset identifier.
        date: Timestamp string.
        state: Ticker state enum value.
        raw_state: Raw integer state code.
    """

    asset: AssetId
    date: str
    state: TickerState
    raw_state: int


@dataclass(frozen=True, slots=True)
class AdjustHistory:
    """Corporate action and adjustment event (dividends, splits, etc.).

    Attributes:
        asset: Asset identifier.
        value: Financial adjustment value or factor.
        adjust_type: Type of adjustment.
        observation: Additional details.
        adjust_date: Adjustment date.
        deliberation_date: Announcement/deliberation date.
        payment_date: Expected payment date.
        affect_price: True if adjustment affects historical price series.
    """

    asset: AssetId
    value: float
    adjust_type: str
    observation: str
    adjust_date: str
    deliberation_date: str
    payment_date: str
    affect_price: bool


@dataclass(frozen=True, slots=True)
class HistoryProgress:
    """Historical-request download progress event (TProgressCallback).

    Attributes:
        asset: Asset the history request refers to.
        progress: Download progress percent (0-100; 100 means the request
            finished — the manual states "from 1 to 100" for GetHistoryTrades).
    """

    asset: AssetId
    progress: int


@dataclass(frozen=True, slots=True)
class InvalidTickerEvent:
    """Event triggered when requested ticker or exchange is rejected as invalid.

    Attributes:
        asset: Rejected asset identifier.
    """

    asset: AssetId


__all__ = [
    "AdjustHistory",
    "AssetInfo",
    "DailyCandle",
    "HistoryProgress",
    "InvalidTickerEvent",
    "TickerStateChange",
    "TradingMessageResult",
]
