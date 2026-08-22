"""Data models for accounts and positions."""

from __future__ import annotations

from dataclasses import dataclass

from profitdll_wrapper._types.core import AssetId


@dataclass(frozen=True, slots=True)
class Account:
    """Represents a trading account or sub-account.

    Attributes:
        account_id: Account identifier string.
        broker_id: Broker ID number (e.g. 3 = Nelogica Simulator).
        sub_account_id: Sub-account identifier string (if applicable).
        broker_name: Formatted broker name.
        owner_name: Account owner name.
        sub_owner_name: Sub-account owner name.
        account_flags: Bitmask account flags.
        account_type: Integer account type flag.
    """

    account_id: str
    broker_id: int
    sub_account_id: str = ""
    broker_name: str = ""
    owner_name: str = ""
    sub_owner_name: str = ""
    account_flags: int = 0
    account_type: int = 0


@dataclass(frozen=True, slots=True)
class Position:
    """Real-time custody position for a given asset.

    Attributes:
        asset: Target asset identifier.
        account_id: Trading account identifier.
        quantity: Net position quantity (positive = long, negative = short, 0 = flat).
        average_price: Open position average price.
        buy_quantity: Total contracts bought today.
        sell_quantity: Total contracts sold today.
        buy_average_price: Daily buy average price.
        sell_average_price: Daily sell average price.
        realized_profit: Realized financial PnL today.
    """

    asset: AssetId
    account_id: str
    quantity: int
    average_price: float
    buy_quantity: int = 0
    sell_quantity: int = 0
    buy_average_price: float = 0.0
    sell_average_price: float = 0.0
    realized_profit: float = 0.0


__all__ = ["Account", "Position"]
