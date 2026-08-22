"""Market data subscriptions and queries mixin."""

from __future__ import annotations

import logging
import math
from ctypes import c_double, c_int64

from profitdll_wrapper._bindings.enums import BookSide, BookUpdateType
from profitdll_wrapper._bindings.errors import NLCode
from profitdll_wrapper._bindings.structures import (
    PG_IS_THEORIC,
    TConnectorAssetIdentifier,
    TConnectorPriceGroup,
)
from profitdll_wrapper._types.book import PriceLevel
from profitdll_wrapper._types.core import AssetId
from profitdll_wrapper.client._base import _ClientBase
from profitdll_wrapper.client._helpers import build_asset_id, validate_exchange

logger = logging.getLogger("profitdll_wrapper.client")


class _ClientMarketDataMixin(_ClientBase):
    """Mixin providing market data subscription and query methods."""

    def subscribe(self, ticker: str, *, exchange: str) -> None:
        """Subscribes to real-time trade feed for `ticker` on `exchange`."""
        validate_exchange(exchange)
        self._check_code(self._backend.subscribe_ticker(ticker, exchange))
        if hasattr(self, "_subscriptions_lock"):
            with self._subscriptions_lock:
                self._active_subscriptions.add(("ticker", ticker, exchange))

    def unsubscribe(self, ticker: str, *, exchange: str) -> None:
        """Unsubscribes from real-time trade feed for `ticker` on `exchange`."""
        validate_exchange(exchange)
        self._check_code(self._backend.unsubscribe_ticker(ticker, exchange))
        if hasattr(self, "_subscriptions_lock"):
            with self._subscriptions_lock:
                self._active_subscriptions.discard(("ticker", ticker, exchange))

    def request_ticker_info(self, ticker: str, *, exchange: str) -> None:
        """Requests asset specification info from exchange."""
        validate_exchange(exchange)
        code = self._backend.request_ticker_info(ticker, exchange)
        self._check_code(code)

    def subscribe_price_depth(self, ticker: str, *, exchange: str) -> None:
        """Subscribes to price depth (price book) for `ticker`."""
        validate_exchange(exchange)
        asset = build_asset_id(ticker, exchange)
        self._check_code(self._backend.subscribe_price_depth(asset))
        if hasattr(self, "_subscriptions_lock"):
            with self._subscriptions_lock:
                self._active_subscriptions.add(("price_depth", ticker, exchange))

    def unsubscribe_price_depth(self, ticker: str, *, exchange: str) -> None:
        """Unsubscribes from price depth for `ticker` on `exchange`."""
        validate_exchange(exchange)
        asset = build_asset_id(ticker, exchange)
        self._check_code(self._backend.unsubscribe_price_depth(asset))
        if hasattr(self, "_subscriptions_lock"):
            with self._subscriptions_lock:
                self._active_subscriptions.discard(("price_depth", ticker, exchange))

    def get_price_depth_side_count(
        self,
        ticker: str,
        side: BookSide | int,
        *,
        exchange: str,
    ) -> int:
        """Returns count of available price levels on specified side of price book."""
        validate_exchange(exchange)
        side_val = int(side.value) if isinstance(side, BookSide) else int(side)
        if side_val not in (0, 1):
            raise ValueError(f"side must be 0 (BUY) or 1 (SELL), got: {side}")

        asset = build_asset_id(ticker, exchange)
        count = int(self._backend.get_price_depth_side_count(asset, side_val))
        return max(count, 0)

    def subscribe_offer_book(self, ticker: str, *, exchange: str) -> None:
        """Subscribes to V2 offer book for `ticker` on `exchange`."""
        validate_exchange(exchange)
        self._check_code(self._backend.subscribe_offer_book(ticker, exchange))
        if hasattr(self, "_subscriptions_lock"):
            with self._subscriptions_lock:
                self._active_subscriptions.add(("offer_book", ticker, exchange))

    def unsubscribe_offer_book(self, ticker: str, *, exchange: str) -> None:
        """Unsubscribes from V2 offer book for `ticker` on `exchange`."""
        validate_exchange(exchange)
        self._check_code(self._backend.unsubscribe_offer_book(ticker, exchange))
        if hasattr(self, "_subscriptions_lock"):
            with self._subscriptions_lock:
                self._active_subscriptions.discard(("offer_book", ticker, exchange))

    def get_price_group(
        self, ticker: str, side: BookSide | int, position: int, *, exchange: str
    ) -> PriceLevel:
        """Reads data for a single price book level outside of callback (thread-safe)."""
        validate_exchange(exchange)
        asset = build_asset_id(ticker, exchange)
        group = TConnectorPriceGroup()
        group.Version = 0
        side_int = int(side)
        code = self._backend.get_price_group(asset, side_int, position, group)
        self._check_code(code)
        is_theoric = bool(group.PriceGroupFlags & PG_IS_THEORIC)
        asset_id = AssetId(ticker=ticker, exchange=exchange)
        return PriceLevel(
            asset=asset_id,
            side=BookSide(side_int),
            update_type=BookUpdateType.EDIT,
            position=position,
            price=float(group.Price),
            count=int(group.Count),
            quantity=int(group.Quantity),
            is_theoretical=is_theoric,
        )

    def get_theoretical_price(self, ticker: str, *, exchange: str) -> float | None:
        """Reads theoretical auction price for an asset (thread-safe).

        Returns ``None`` when the DLL reports no usable value: ``0.0`` is an
        economically meaningful price and must not double as a sentinel.
        """
        validate_exchange(exchange)
        asset = build_asset_id(ticker, exchange)
        return self._read_theoretical_price(asset)

    def _read_theoretical_price(self, asset: TConnectorAssetIdentifier) -> float | None:
        """Reads theoretical price via GetTheoreticalValues API call."""
        out_price = c_double()
        out_qty = c_int64()
        code = self._backend.get_theoretical_values(asset, out_price, out_qty)
        if code != int(NLCode.OK):
            return None
        value = float(out_price.value)
        if math.isnan(value) or math.isinf(value) or value <= 0.0:
            return None
        return value

    def get_history_trades(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        *,
        exchange: str = "B",
    ) -> None:
        """Requests historical tick-by-tick trades streaming for an asset.

        Delivered asynchronously via HISTORICAL_TRADE events.
        """
        validate_exchange(exchange)
        code = self._backend.get_history_trades(ticker, exchange, start_date, end_date)
        self._check_code(code)

    def get_last_daily_close(
        self,
        ticker: str,
        *,
        exchange: str = "B",
        adjusted: bool = True,
    ) -> float:
        """Queries previous session closing price for an asset."""
        from ctypes import byref, c_double

        validate_exchange(exchange)
        out_close = c_double()
        code = self._backend.get_last_daily_close(
            ticker, exchange, byref(out_close), 1 if adjusted else 0
        )
        self._check_code(code)
        return float(out_close.value)

    def subscribe_adjust_history(
        self,
        ticker: str,
        *,
        exchange: str = "B",
    ) -> None:
        """Subscribes to corporate actions and price adjustment history.

        Delivered asynchronously via ADJUST_HISTORY events.
        """
        validate_exchange(exchange)
        self._check_code(self._backend.subscribe_adjust_history(ticker, exchange))
        if hasattr(self, "_subscriptions_lock"):
            with self._subscriptions_lock:
                self._active_subscriptions.add(("adjust_history", ticker, exchange))

    def unsubscribe_adjust_history(
        self,
        ticker: str,
        *,
        exchange: str = "B",
    ) -> None:
        """Unsubscribes from corporate actions and price adjustment history."""
        validate_exchange(exchange)
        self._check_code(self._backend.unsubscribe_adjust_history(ticker, exchange))
        if hasattr(self, "_subscriptions_lock"):
            with self._subscriptions_lock:
                self._active_subscriptions.discard(("adjust_history", ticker, exchange))

    def resubscribe_all(self) -> int:
        """Restores all active market data subscriptions registered on client.

        Returns:
            int: Number of subscriptions successfully restored.
        """
        if not hasattr(self, "_subscriptions_lock"):
            return 0

        with self._subscriptions_lock:
            subs = list(self._active_subscriptions)

        if not subs:
            logger.info("No active subscriptions to restore.")
            return 0

        logger.info("Starting auto-resubscribe for %d active subscriptions...", len(subs))
        success_count = 0
        for sub_type, ticker, exchange in subs:
            try:
                if sub_type == "ticker":
                    self._backend.subscribe_ticker(ticker, exchange)
                elif sub_type == "price_depth":
                    asset = build_asset_id(ticker, exchange)
                    self._backend.subscribe_price_depth(asset)
                elif sub_type == "offer_book":
                    self._backend.subscribe_offer_book(ticker, exchange)
                elif sub_type == "adjust_history":
                    self._backend.subscribe_adjust_history(ticker, exchange)
                success_count += 1
            except Exception as exc:
                logger.error(
                    "Failed to resubscribe %s (%s, %s): %s", sub_type, ticker, exchange, exc
                )

        logger.info(
            "Auto-resubscribe finished: %d/%d subscriptions successfully restored.",
            success_count,
            len(subs),
        )
        return success_count
