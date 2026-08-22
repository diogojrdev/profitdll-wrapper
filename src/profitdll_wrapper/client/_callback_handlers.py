"""Native ctypes callback handlers executing on ProfitDLL's ConnectorThread."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from profitdll_wrapper._bindings.callbacks import TC_IS_EDIT
from profitdll_wrapper._bindings.enums import (
    OK_RESULT_BY_STATE,
    ActivationResult,
    BookSide,
    BookUpdateType,
    ConnectionState,
    LoginResult,
    MarketResult,
    OrderSide,
    OrderStatus,
    OrderType,
    RoutingResult,
    SystemHealthState,
    TickerState,
)
from profitdll_wrapper._bindings.errors import NLCode
from profitdll_wrapper._bindings.structures import (
    TAssetID,
    TConnectorAccountIdentifier,
    TConnectorAssetIdentifier,
    TConnectorOrderIdentifier,
    TConnectorOrderOut,
    TConnectorTrade,
)
from profitdll_wrapper._types.book import PriceBookSnapshot, PriceLevel
from profitdll_wrapper._types.core import AssetId, Trade
from profitdll_wrapper._types.messages import (
    AdjustHistory,
    AssetInfo,
    DailyCandle,
    InvalidTickerEvent,
    TickerStateChange,
    TradingMessageResult,
)
from profitdll_wrapper._types.orders import Order
from profitdll_wrapper.client._base import _ClientBase

logger = logging.getLogger("profitdll_wrapper.client")

# V2 binary offer array layout (vendor ABI): an 8-byte header (count, buffer
# size) followed by fixed-stride records of 53 bytes (30-byte fixed part plus
# a length-prefixed date string).
_OFFER_HEADER_BYTES = 8
_OFFER_RECORD_STRIDE = 53
_OFFER_RECORD_FIXED_BYTES = 30
_BUFFER_SLACK_BYTES = 100

# Retry budget for GetOrderDetails when the DLL reports a transient failure.
_ORDER_DETAILS_RETRIES = 5


def _descript_offer_array_v2(offer_array_ptr: Any) -> list[tuple[float, int, int, int, str]]:
    """Decodes the V2 binary offer array returned by ProfitDLL."""
    if not bool(offer_array_ptr):
        return []
    try:
        import struct
        from ctypes import POINTER, c_char, cast

        header = cast(offer_array_ptr, POINTER(c_char * _OFFER_HEADER_BYTES)).contents
        qtd_offer, pointer_size = struct.unpack("ii", header.raw)
        if qtd_offer <= 0:
            return []

        max_size = pointer_size + _BUFFER_SLACK_BYTES
        full_buffer = cast(offer_array_ptr, POINTER(c_char * max_size)).contents
        offer_array = bytearray(full_buffer)
        frame = bytearray(
            offer_array[
                _OFFER_HEADER_BYTES : _OFFER_HEADER_BYTES + (qtd_offer * _OFFER_RECORD_STRIDE)
            ]
        )
        start = 0
        offer_list: list[tuple[float, int, int, int, str]] = []
        for _ in range(qtd_offer):
            price, qty, agent, offer_id, date_len = struct.unpack(
                "=dqiqH", frame[start : start + _OFFER_RECORD_FIXED_BYTES]
            )
            start += _OFFER_RECORD_FIXED_BYTES
            date_bytes = struct.unpack(f"{date_len}s", frame[start : start + date_len])[0]
            start += date_len
            try:
                date_str = date_bytes.decode("utf-8", errors="replace")
            except Exception:
                date_str = str(date_bytes)
            offer_list.append((price, qty, agent, offer_id, date_str))
        return offer_list
    except Exception as e:
        logger.error("Failed to decode offer array v2: %s", e)
        return []


class _ClientCallbackMixin(_ClientBase):
    """Mixin with all thin ctypes callbacks that register and enqueue events."""

    _ORDER_STATUS_MAP: ClassVar[dict[int, OrderStatus]] = {
        0: OrderStatus.NEW,
        1: OrderStatus.PARTIALLY_FILLED,
        2: OrderStatus.FILLED,
        3: OrderStatus.DONE_FOR_DAY,
        4: OrderStatus.CANCELED,
        5: OrderStatus.REPLACED,
        6: OrderStatus.PENDING_CANCEL,
        7: OrderStatus.STOPPED,
        8: OrderStatus.REJECTED,
        9: OrderStatus.SUSPENDED,
        10: OrderStatus.PENDING_NEW,
        11: OrderStatus.CALCULATED,
        12: OrderStatus.EXPIRED,
        13: OrderStatus.ACCEPTED_FOR_BIDDING,
        14: OrderStatus.PENDING_REPLACE,
        15: OrderStatus.PARTIALLY_FILLED_CANCELED,
        16: OrderStatus.RECEIVED,
        17: OrderStatus.PARTIALLY_FILLED_EXPIRED,
        18: OrderStatus.PARTIALLY_FILLED_REJECTED,
        200: OrderStatus.UNKNOWN,
        201: OrderStatus.HADES_CREATED,
        202: OrderStatus.BROKER_SENT,
        203: OrderStatus.CLIENT_CREATED,
        204: OrderStatus.ORDER_NOT_CREATED,
        205: OrderStatus.CANCELED_BY_ADMIN,
        206: OrderStatus.DELAY_FIX_GATEWAY,
        207: OrderStatus.SCHEDULED_ORDER,
    }
    _ORDER_STATUS_STR_MAP: ClassVar[dict[str, OrderStatus]] = {
        "0": OrderStatus.NEW,
        "new": OrderStatus.NEW,
        "1": OrderStatus.PARTIALLY_FILLED,
        "partiallyfilled": OrderStatus.PARTIALLY_FILLED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "2": OrderStatus.FILLED,
        "filled": OrderStatus.FILLED,
        "3": OrderStatus.DONE_FOR_DAY,
        "doneforday": OrderStatus.DONE_FOR_DAY,
        "4": OrderStatus.CANCELED,
        "canceled": OrderStatus.CANCELED,
        "cancelled": OrderStatus.CANCELED,
        "5": OrderStatus.REPLACED,
        "replaced": OrderStatus.REPLACED,
        "6": OrderStatus.PENDING_CANCEL,
        "pendingcancel": OrderStatus.PENDING_CANCEL,
        "7": OrderStatus.STOPPED,
        "stopped": OrderStatus.STOPPED,
        "8": OrderStatus.REJECTED,
        "rejected": OrderStatus.REJECTED,
        "9": OrderStatus.SUSPENDED,
        "suspended": OrderStatus.SUSPENDED,
        "12": OrderStatus.EXPIRED,
        "expired": OrderStatus.EXPIRED,
    }

    def _on_state(self, n_state_type: int, n_result: int) -> None:
        """Thin state callback: resolves the per-domain event/future.

        Records the last result per domain (for timeout diagnostics), classifies
        terminal states as a login failure (``_login_error``) so ``connect()``
        fails fast with an informative AuthError, and sets the ``threading.Event``
        when the result matches the domain's expected OK value.
        """

        try:
            state = ConnectionState(n_state_type)
        except ValueError:
            logger.debug("Unknown connection state: %s", n_state_type)
            return

        # Skip state notifications fired while tearing down (e.g. the DISCONNECTED
        # event emitted by DLLFinalize itself) so disconnect stays quiet.
        from profitdll_wrapper._bindings.functions import _interpreter_shutting_down

        if getattr(self, "_tearing_down", False) or _interpreter_shutting_down:
            return

        logger.info("State callback: state=%s (%s) result=%s", state.name, n_state_type, n_result)

        # Always track the last observed result per domain for timeout diagnostics.
        if hasattr(self, "_record_state_result"):
            self._record_state_result(state, n_result)

        # Classify terminal failures so connect() fails fast instead of timing out.
        self._classify_state_failure(state, n_result)

        # Auto-resubscribe on Market Data reconnect after a prior successful connect.
        if (
            state is ConnectionState.MARKET_DATA
            and n_result == int(MarketResult.CONNECTED)
            and getattr(self, "_has_connected_once", False)
            and getattr(self, "_auto_resubscribe", True)
        ):
            logger.info("Market Data reconnection detected! Executing auto-resubscribe...")
            self.resubscribe_all()

        ok = OK_RESULT_BY_STATE.get(state)
        evt = self._state_events.get(state)
        if evt is not None and ok is not None and n_result == ok:
            evt.set()

    @staticmethod
    def _is_terminal_failure(state: ConnectionState, n_result: int) -> bool:
        """True when a state/result pair is a terminal connection failure.

        Transient states (CONNECTING, WAITING, PERFORMANCE_WARNING) do NOT count
        as failures: the domain may still reach OK later. Hard failures
        (disconnected, denied, invalid) are terminal so connect() can abort
        promptly with a useful error instead of waiting for the full timeout.
        """
        if state is ConnectionState.LOGIN:
            return n_result != int(LoginResult.CONNECTED)
        if state is ConnectionState.ROUTING:
            return n_result in (
                int(RoutingResult.DISCONNECTED),
                int(RoutingResult.BROKER_DISCONNECTED),
            )
        if state is ConnectionState.MARKET_DATA:
            return n_result in (
                int(MarketResult.DISCONNECTED),
                int(MarketResult.NOT_LOGGED),
                int(MarketResult.PARTIAL_CONNECTED),
            )
        if state is ConnectionState.MARKET_LOGIN:
            return n_result == int(ActivationResult.INVALID)
        return False

    def _classify_state_failure(self, state: ConnectionState, n_result: int) -> None:
        """Records a terminal failure via _set_login_error and logs a helpful hint.

        PERFORMANCE_WARNING (MarketData=5) is a transient degradation, not a
        failure, so it is only logged here.
        """
        if state is ConnectionState.MARKET_DATA and n_result == int(
            MarketResult.PERFORMANCE_WARNING
        ):
            logger.warning("Market data: server performance degradation (5).")
            return

        if not self._is_terminal_failure(state, n_result):
            return

        if state is ConnectionState.MARKET_DATA and n_result == int(MarketResult.NOT_LOGGED):
            logger.error(
                "Market data returned NOT_LOGGED (3). Try using mode='routing' if server requires full authentication."
            )
        elif state is ConnectionState.MARKET_DATA and n_result == int(
            MarketResult.PARTIAL_CONNECTED
        ):
            logger.critical("Market data: local callback delivery frozen (6) - risk of data loss.")
        elif state is ConnectionState.ROUTING:
            logger.error(
                "Routing returned %s (%s). Verify broker/account credentials and server availability.",
                RoutingResult(n_result).name,
                n_result,
            )

        self._set_login_error(state, n_result)

    def _on_trade(
        self,
        asset: TConnectorAssetIdentifier,
        p_trade: int,
        flags: int,
    ) -> None:
        """Thin trade callback: translates/copies (synchronous) and enqueues."""
        try:
            asset_id = AssetId.from_native(asset)
            is_edit = bool(flags & TC_IS_EDIT)

            raw = TConnectorTrade()
            raw.Version = 0
            code = self._backend.translate_trade(p_trade, raw)
            if code != int(NLCode.OK):
                logger.warning("TranslateTrade failed (code=%#x) for %s", code, asset_id.ticker)
                return

            trade = Trade.from_native(asset_id, raw, is_edit=is_edit)
            self._dispatcher.enqueue_trade(trade)
        except Exception:
            logger.exception("Error in trade callback")

    def _on_price_depth(
        self,
        asset: TConnectorAssetIdentifier,
        side: int,
        position: int,
        update_type: int,
    ) -> None:
        """Thin price-depth callback: copies data (synchronous) and enqueues (Pure Enqueue)."""
        try:
            asset_id = AssetId.from_native(asset)
            try:
                side_e = BookSide(side)
                ut = BookUpdateType(update_type)
            except ValueError:
                logger.debug("PriceDepth: side/updateType fora do enum: %s/%s", side, update_type)
                return

            if ut is BookUpdateType.FULL_BOOK:
                snapshot = PriceBookSnapshot(asset=asset_id, buy_levels=(), sell_levels=())
                self._dispatcher.enqueue_price_snapshot(snapshot)
                return

            level = PriceLevel(
                asset=asset_id,
                side=side_e,
                update_type=ut,
                position=position,
                price=0.0,
                count=0,
                quantity=0,
            )
            self._dispatcher.enqueue_price_level(level)
        except Exception:
            logger.exception("Error in price depth callback")

    def _on_daily(
        self,
        asset: TAssetID,
        date: str,
        s_open: float,
        s_high: float,
        s_low: float,
        s_close: float,
        s_vol: float,
        s_ajuste: float,
        s_max_limit: float,
        s_min_limit: float,
        s_vol_buyer: float,
        s_vol_seller: float,
        n_qtd: int,
        n_negocios: int,
        n_contratos_open: int,
        n_qtd_buyer: int,
        n_qtd_seller: int,
        n_neg_buyer: int,
        n_neg_seller: int,
    ) -> None:
        """Thin daily-candle callback: copies fields and enqueues."""
        try:
            asset_id = AssetId.from_legacy(asset)
            candle = DailyCandle(
                asset=asset_id,
                date=date or "",
                open=s_open,
                high=s_high,
                low=s_low,
                close=s_close,
                volume=s_vol,
                adjustment=s_ajuste,
                max_limit=s_max_limit,
                min_limit=s_min_limit,
                volume_buyer=s_vol_buyer,
                volume_seller=s_vol_seller,
                quantity=n_qtd,
                trades=n_negocios,
                open_interest=n_contratos_open,
                quantity_buyer=n_qtd_buyer,
                quantity_seller=n_qtd_seller,
                trades_buyer=n_neg_buyer,
                trades_seller=n_neg_seller,
            )
            self._dispatcher.enqueue_daily(candle)
        except Exception:
            logger.exception("Error in daily callback")

    def _on_order_history_loaded(
        self,
        account_id: TConnectorAccountIdentifier,
    ) -> None:
        """Thin order-history callback: signals download completion."""
        try:
            acc = str(account_id.AccountID or "")
            logger.info("Order history loaded for account %s", acc)
            evt = getattr(self, "_order_history_loaded", None)
            if evt is not None:
                evt.set()
        except Exception:
            logger.exception("Error in order history callback")

    def _on_order_callback(
        self,
        order_id: TConnectorOrderIdentifier,
    ) -> None:
        """Thin V1 order callback: receives ID, calls GetOrderDetails, enqueues."""
        from datetime import datetime

        try:
            order_out = TConnectorOrderOut()
            order_out.Version = 0
            order_out.OrderID.Version = order_id.Version
            order_out.OrderID.LocalOrderID = order_id.LocalOrderID
            order_out.OrderID.ClOrderID = order_id.ClOrderID

            ret = self._backend.get_order_details(order_out)
            if ret != 0:
                for _ in range(_ORDER_DETAILS_RETRIES):
                    ret = self._backend.get_order_details(order_out)
                    if ret == 0:
                        break
            if ret != 0:
                logger.warning(
                    "GetOrderDetails (pass 1) returned %s (LocalOrderID=%s, ClOrderID=%s)",
                    ret,
                    order_id.LocalOrderID,
                    order_id.ClOrderID,
                )
                if order_id.LocalOrderID:
                    fallback_order = Order(
                        id=int(order_id.LocalOrderID),
                        cl_ord_id=str(order_id.ClOrderID or ""),
                        asset=AssetId(ticker="", exchange=""),
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        status=OrderStatus.NEW,
                        price=0.0,
                        quantity=1,
                        traded_quantity=0,
                        leaves_quantity=1,
                        average_price=0.0,
                        account_id="",
                        timestamp=datetime.now(),
                    )
                    self._dispatcher.enqueue_order(fallback_order)
                return

            ticker_len = order_out.AssetID.TickerLength
            exchange_len = order_out.AssetID.ExchangeLength
            text_len = order_out.TextMessageLength

            if ticker_len and ticker_len > 0:
                order_out.AssetID.Ticker = " " * ticker_len
            if exchange_len and exchange_len > 0:
                order_out.AssetID.Exchange = " " * exchange_len
            if text_len and text_len > 0:
                order_out.TextMessage = " " * text_len

            ret = self._backend.get_order_details(order_out)
            if ret != 0:
                logger.warning("GetOrderDetails (pass 2) returned %s", ret)
                return

            ticker = (order_out.AssetID.Ticker or "").strip()
            exchange = (order_out.AssetID.Exchange or "").strip()
            asset_id = AssetId(ticker=ticker, exchange=exchange)

            side_e = OrderSide.BUY if order_out.OrderSide == 1 else OrderSide.SELL

            otype_map = {1: OrderType.MARKET, 2: OrderType.LIMIT, 4: OrderType.STOP}
            order_type_e = otype_map.get(order_out.OrderType, OrderType.LIMIT)

            status_e = self._ORDER_STATUS_MAP.get(order_out.OrderStatus, OrderStatus.NEW)

            profit_id = order_out.OrderID.LocalOrderID or 0
            cl_ord_id = order_out.OrderID.ClOrderID or ""
            account_id = order_out.AccountID.AccountID or ""
            text_msg = (order_out.TextMessage or "").strip()

            logger.info(
                "OrderCallback: id=%s asset=%s status=%s side=%s qty=%s traded=%s price=%.2f avg=%.2f msg=%s",
                profit_id,
                ticker,
                status_e.name,
                side_e.name,
                order_out.Quantity,
                order_out.TradedQuantity,
                order_out.Price,
                order_out.AveragePrice,
                text_msg,
            )

            order = Order(
                id=int(profit_id),
                cl_ord_id=cl_ord_id,
                asset=asset_id,
                side=side_e,
                order_type=order_type_e,
                status=status_e,
                price=float(order_out.Price),
                quantity=int(order_out.Quantity),
                traded_quantity=int(order_out.TradedQuantity),
                leaves_quantity=int(order_out.LeavesQuantity),
                average_price=float(order_out.AveragePrice),
                account_id=account_id,
                timestamp=datetime.now(),
                text_message=text_msg,
            )
            self._dispatcher.enqueue_order(order)
        except Exception:
            logger.exception("Error in V1 order callback")

    def _on_order_change_v2(
        self,
        r_asset: TAssetID,
        n_corretora: int,
        n_qtd: int,
        n_traded_qtd: int,
        n_leaves_qtd: int,
        n_side: int,
        n_validity: int,
        d_price: float,
        d_stop_price: float,
        d_avg_price: float,
        n_profit_id: int,
        tipo_ordem: str,
        conta: str,
        titular: str,
        cl_ord_id: str,
        status: str,
        last_update: str,
        close_date: str,
        validity_date: str,
        text_message: str,
    ) -> None:
        """Thin V2 order-change callback: receives all data via C params without reentrancy."""
        from datetime import datetime

        try:
            asset_id = AssetId.from_legacy(r_asset)
            side_e = OrderSide.BUY if n_side == 1 else OrderSide.SELL

            st_key = (status or "").strip().lower()
            status_e = self._ORDER_STATUS_STR_MAP.get(st_key, OrderStatus.NEW)
            if st_key.isdigit():
                st_int = int(st_key)
                status_e = self._ORDER_STATUS_MAP.get(st_int, status_e)

            order = Order(
                id=int(n_profit_id),
                cl_ord_id=str(cl_ord_id or ""),
                asset=asset_id,
                side=side_e,
                order_type=OrderType.LIMIT,
                status=status_e,
                price=float(d_price),
                quantity=int(n_qtd),
                traded_quantity=int(n_traded_qtd),
                leaves_quantity=int(n_leaves_qtd),
                average_price=float(d_avg_price),
                account_id=str(conta or ""),
                timestamp=datetime.now(),
                text_message=str(text_message or "").strip(),
            )
            logger.info(
                "OrderChangeV2: id=%s asset=%s status=%s side=%s qty=%s traded=%s price=%.2f avg=%.2f msg=%s",
                n_profit_id,
                asset_id.ticker,
                status_e.name,
                side_e.name,
                n_qtd,
                n_traded_qtd,
                d_price,
                d_avg_price,
                text_message,
            )
            self._dispatcher.enqueue_order(order)
        except Exception:
            logger.exception("Error in V2 order callback")

    def _on_offer_book_v2(
        self,
        asset_id_raw: TAssetID,
        n_action: int,
        n_position: int,
        side: int,
        n_qtd: int,
        n_agent: int,
        n_offer_id: int,
        s_price: float,
        b_has_price: int,
        b_has_qtd: int,
        b_has_date: int,
        b_has_offer_id: int,
        b_has_agent: int,
        date: str,
        p_array_sell: Any,
        p_array_buy: Any,
    ) -> None:
        """Thin V2 offer-book callback: reads binary offers from memory and enqueues."""
        try:
            asset_id = AssetId.from_legacy(asset_id_raw)
            if not asset_id.ticker:
                return

            buy_levels: list[PriceLevel] = []
            sell_levels: list[PriceLevel] = []

            if bool(p_array_buy):
                buy_data = _descript_offer_array_v2(p_array_buy)
                for pos, (price, qty, _agent, _offer_id, _date_str) in enumerate(
                    reversed(buy_data)
                ):
                    if price > 0 and qty > 0:
                        buy_levels.append(
                            PriceLevel(
                                asset=asset_id,
                                side=BookSide.BUY,
                                update_type=BookUpdateType.FULL_BOOK,
                                position=pos,
                                price=float(price),
                                count=1,
                                quantity=int(qty),
                            )
                        )

            if bool(p_array_sell):
                sell_data = _descript_offer_array_v2(p_array_sell)
                for pos, (price, qty, _agent, _offer_id, _date_str) in enumerate(
                    reversed(sell_data)
                ):
                    if price > 0 and qty > 0:
                        sell_levels.append(
                            PriceLevel(
                                asset=asset_id,
                                side=BookSide.SELL,
                                update_type=BookUpdateType.FULL_BOOK,
                                position=pos,
                                price=float(price),
                                count=1,
                                quantity=int(qty),
                            )
                        )

            if buy_levels or sell_levels:
                snapshot = PriceBookSnapshot(
                    asset=asset_id,
                    buy_levels=tuple(buy_levels),
                    sell_levels=tuple(sell_levels),
                )
                self._dispatcher.enqueue_price_snapshot(snapshot)
        except Exception:
            logger.exception("Error in V2 offer book callback")

    def _on_asset_position_list(
        self,
        account: Any,
        asset: Any,
        last_event: int,
    ) -> None:
        """Thin position-change callback: fetches the updated position and enqueues."""
        try:
            acc_id = str(account.AccountID or "")
            broker_id = int(account.BrokerID) if account.BrokerID else None
            ticker = str(asset.Ticker or "").strip()
            exchange = str(asset.Exchange or "").strip()

            if not ticker or ticker == "-1":
                return

            pos = self.get_position(ticker, exchange=exchange, account=acc_id, broker_id=broker_id)
            self._dispatcher.enqueue_position(pos)
        except Exception:
            logger.exception("Error in position list callback")

    def _on_trading_message(self, res_ptr: Any) -> None:
        """Thin trading/risk message callback."""
        try:
            if not res_ptr:
                return
            res = res_ptr.contents if hasattr(res_ptr, "contents") else res_ptr
            msg = TradingMessageResult.from_native(res)
            self._dispatcher.enqueue_trading_message(msg)
        except Exception:
            logger.exception("Error in trading message callback")

    def _on_asset_list_info_v2(
        self,
        r_asset: TAssetID,
        pwc_name: str,
        pwc_description: str,
        n_min_order_qty: int,
        n_max_order_qty: int,
        n_lote: int,
        st_security_type: int,
        ss_security_sub_type: int,
        d_min_price_increment: float,
        d_contract_multiplier: float,
        str_valid_date: str,
        str_isin: str,
        str_setor: str,
        str_sub_setor: str,
        str_segmento: str,
    ) -> None:
        """Thin V2 asset-info callback."""
        try:
            asset_id = AssetId.from_legacy(r_asset)
            if not asset_id.ticker:
                return

            info = AssetInfo(
                asset=asset_id,
                name=str(pwc_name or "").strip(),
                description=str(pwc_description or "").strip(),
                min_order_qty=int(n_min_order_qty),
                max_order_qty=int(n_max_order_qty),
                lot_size=int(n_lote),
                security_type=int(st_security_type),
                security_subtype=int(ss_security_sub_type),
                min_price_increment=float(d_min_price_increment),
                contract_multiplier=float(d_contract_multiplier),
                valid_date=str(str_valid_date or "").strip(),
                isin=str(str_isin or "").strip(),
                sector=str(str_setor or "").strip(),
                subsector=str(str_sub_setor or "").strip(),
                segment=str(str_segmento or "").strip(),
            )
            self._dispatcher.enqueue_asset_info(info)
        except Exception:
            logger.exception("Error in V2 asset list info callback")

    def _on_change_state_ticker(
        self,
        r_asset: TAssetID,
        pwc_date: str,
        n_state: int,
    ) -> None:
        """Thin ticker-state-change callback (auction, closed, etc.)."""
        try:
            asset_id = AssetId.from_legacy(r_asset)
            if not asset_id.ticker:
                return

            try:
                state_e = TickerState(int(n_state))
            except ValueError:
                state_e = TickerState.UNKNOWN

            change = TickerStateChange(
                asset=asset_id,
                date=str(pwc_date or "").strip(),
                state=state_e,
                raw_state=int(n_state),
            )
            self._dispatcher.enqueue_ticker_state(change)
        except Exception:
            logger.exception("Error in change state ticker callback")

    def _on_health_change(self, n_state: int) -> None:
        """Thin DLL health (watchdog) change callback."""
        try:
            try:
                state = SystemHealthState(int(n_state))
            except ValueError:
                state = SystemHealthState.FROZEN
            self._dispatcher.enqueue_health_change(state)
        except Exception:
            logger.exception("Error in health status callback")

    def _on_history_trade(
        self,
        asset: TConnectorAssetIdentifier,
        p_trade: int,
        flags: int,
    ) -> None:
        """Thin historical-trade callback: translates/copies (synchronous) and enqueues as HISTORICAL_TRADE."""
        try:
            asset_id = AssetId.from_native(asset)
            is_edit = bool(flags & TC_IS_EDIT)

            raw = TConnectorTrade()
            raw.Version = 0
            code = self._backend.translate_trade(p_trade, raw)
            if code != int(NLCode.OK):
                logger.warning(
                    "TranslateTrade failed on historical trade (code=%#x) for %s",
                    code,
                    asset_id.ticker,
                )
                return

            trade = Trade.from_native(asset_id, raw, is_edit=is_edit)
            self._dispatcher.enqueue_historical_trade(trade)
        except Exception:
            logger.exception("Error in history trade callback")

    def _on_adjust_history_v2(
        self,
        asset: TAssetID,
        d_value: float,
        str_adjust_type: str | None,
        str_observ: str | None,
        dt_ajuste: str | None,
        dt_deliber: str | None,
        dt_pagamento: str | None,
        n_affect_price: int,
    ) -> None:
        """Thin adjust/corporate-action history callback."""
        try:
            asset_id = AssetId.from_legacy(asset)
            adjust = AdjustHistory(
                asset=asset_id,
                value=float(d_value),
                adjust_type=str(str_adjust_type or "").strip(),
                observation=str(str_observ or "").strip(),
                adjust_date=str(dt_ajuste or "").strip(),
                deliberation_date=str(dt_deliber or "").strip(),
                payment_date=str(dt_pagamento or "").strip(),
                affect_price=bool(n_affect_price),
            )
            self._dispatcher.enqueue_adjust_history(adjust)
        except Exception:
            logger.exception("Error in adjust history callback")

    def _on_invalid_ticker(
        self,
        asset_ptr: Any,
    ) -> None:
        """Thin invalid ticker/exchange notification callback."""
        try:
            if not bool(asset_ptr):
                return
            asset_id = AssetId.from_native(asset_ptr.contents)
            event = InvalidTickerEvent(asset=asset_id)
            self._dispatcher.enqueue_invalid_ticker(event)
        except Exception:
            logger.exception("Error in invalid ticker callback")
