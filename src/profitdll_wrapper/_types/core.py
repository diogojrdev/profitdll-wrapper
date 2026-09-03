"""Core data models: Asset identifiers and Trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from profitdll_wrapper._bindings.structures import (
        SystemTime,
        TConnectorAssetIdentifier,
        TConnectorTrade,
    )


@dataclass(frozen=True, slots=True)
class AssetId:
    """Asset identifier (ticker symbol and exchange code).

    Attributes:
        ticker: Ticker symbol (e.g. "WDOFUT", "PETR4").
        exchange: Exchange code (e.g. "B" for Bovespa, "F" for BMF).
    """

    ticker: str
    exchange: str

    @classmethod
    def from_native(cls, asset: TConnectorAssetIdentifier) -> AssetId:
        """Constructs AssetId from native TConnectorAssetIdentifier structure."""
        return cls(
            ticker=asset.Ticker or "",
            exchange=asset.Exchange or "",
        )

    @classmethod
    def from_legacy(cls, asset: Any) -> AssetId:
        """Constructs AssetId from legacy TAssetID / TAssetIDRec structure."""
        ticker = getattr(asset, "pwcTicker", None) or getattr(asset, "ticker", "")
        exchange = getattr(asset, "pwcBolsa", None) or getattr(asset, "bolsa", "")
        return cls(
            ticker=str(ticker or "").strip(),
            exchange=str(exchange or "").strip(),
        )


def _systemtime_to_datetime(st: SystemTime) -> datetime:
    """Converts Win32 SystemTime structure to Python datetime object."""
    year = int(st.wYear)
    if year == 0:
        return datetime.fromtimestamp(0)
    return datetime(
        year,
        int(st.wMonth),
        int(st.wDay),
        int(st.wHour),
        int(st.wMinute),
        int(st.wSecond),
        int(st.wMilliseconds) * 1000,
    )


@dataclass(frozen=True, slots=True)
class Trade:
    """Executed trade market data event.

    Attributes:
        asset: Target asset identifier.
        trade_number: Sequential trade ID.
        price: Trade execution price.
        quantity: Traded contract volume.
        volume: Total financial volume.
        buy_agent: Buyer broker/agent ID.
        sell_agent: Seller broker/agent ID.
        trade_type: Trade type classification.
        timestamp: Execution timestamp.
        is_edit: True if trade is a correction of a previous trade.
        last_packet: True on the final trade of a history request
            (TC_LAST_PACKET flag of SetHistoryTradeCallbackV2, vendor manual).
            Informational only — do not treat it as the sole completion signal
            for requests that return zero trades.
    """

    asset: AssetId
    trade_number: int
    price: float
    quantity: int
    volume: float
    buy_agent: int
    sell_agent: int
    trade_type: int
    timestamp: datetime
    is_edit: bool
    last_packet: bool = False

    @property
    def date(self) -> datetime:
        """Alias for timestamp."""
        return self.timestamp

    @classmethod
    def from_native(
        cls,
        asset: AssetId,
        raw: TConnectorTrade,
        *,
        is_edit: bool = False,
        last_packet: bool = False,
    ) -> Trade:
        """Constructs Trade instance from translated native TConnectorTrade."""
        return cls(
            asset=asset,
            trade_number=int(raw.TradeNumber),
            price=float(raw.Price),
            quantity=int(raw.Quantity),
            volume=float(raw.Volume),
            buy_agent=int(raw.BuyAgent),
            sell_agent=int(raw.SellAgent),
            trade_type=int(raw.TradeType),
            timestamp=_systemtime_to_datetime(raw.TradeDate),
            is_edit=is_edit,
            last_packet=last_packet,
        )


__all__ = ["AssetId", "Trade", "_systemtime_to_datetime"]
