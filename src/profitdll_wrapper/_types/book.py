"""Data models for order book and price depth events."""

from __future__ import annotations

from dataclasses import dataclass, field

from profitdll_wrapper._bindings.enums import BookSide, BookUpdateType
from profitdll_wrapper._types.core import AssetId


@dataclass(frozen=True, slots=True)
class PriceLevel:
    """A price level change event in price depth.

    Attributes:
        asset: Target asset identifier.
        side: Book side (BUY, SELL, BOTH).
        update_type: Change operation type (ADD, EDIT, DELETE, etc.).
        position: Price level position index (0 = top of book).
        price: Price level price.
        count: Number of order offers at level.
        quantity: Aggregated contract volume at level.
        is_theoretical: True if level price is theoretical value.
    """

    asset: AssetId
    side: BookSide
    update_type: BookUpdateType
    position: int
    price: float
    count: int
    quantity: int
    is_theoretical: bool = False


@dataclass(frozen=True, slots=True)
class PriceBookSnapshot:
    """Full snapshot of order price book.

    Attributes:
        asset: Target asset identifier.
        buy_levels: Ordered buy levels (bids).
        sell_levels: Ordered sell levels (asks).
    """

    asset: AssetId
    buy_levels: tuple[PriceLevel, ...] = field(default_factory=tuple)
    sell_levels: tuple[PriceLevel, ...] = field(default_factory=tuple)


__all__ = ["PriceBookSnapshot", "PriceLevel"]
