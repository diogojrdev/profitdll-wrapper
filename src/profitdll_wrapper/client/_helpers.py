"""Helper functions and constructors for ctypes structures."""

from __future__ import annotations

from profitdll_wrapper._bindings.enums import ExchangeCode
from profitdll_wrapper._bindings.structures import (
    TConnectorAccountIdentifier,
    TConnectorAssetIdentifier,
    TConnectorOrderIdentifier,
)


def validate_exchange(exchange: str) -> None:
    """Validates if exchange string is a valid ExchangeCode."""
    try:
        ExchangeCode(exchange)
    except ValueError as exc:
        raise ValueError(
            f"Unknown exchange {exchange!r}. Valid exchange codes: "
            f"{[e.value for e in ExchangeCode]}"
        ) from exc


def build_asset_id(ticker: str, exchange: str) -> TConnectorAssetIdentifier:
    """Constructs TConnectorAssetIdentifier for DLL calls."""
    asset = TConnectorAssetIdentifier()
    asset.Version = 0
    asset.Ticker = ticker
    asset.Exchange = exchange
    asset.FeedType = 0
    return asset


def build_account_id(account: str, broker_id: int) -> TConnectorAccountIdentifier:
    """Constructs TConnectorAccountIdentifier for DLL calls."""
    acc = TConnectorAccountIdentifier()
    acc.Version = 0
    acc.BrokerID = broker_id
    acc.AccountID = account
    acc.SubAccountID = ""
    acc.Reserved = 0
    return acc


def build_order_id(order_id: int, cl_ord_id: str = "") -> TConnectorOrderIdentifier:
    """Constructs TConnectorOrderIdentifier for DLL calls."""
    ord_id = TConnectorOrderIdentifier()
    ord_id.Version = 0
    ord_id.LocalOrderID = order_id
    ord_id.ClOrderID = cl_ord_id if cl_ord_id else None
    return ord_id
