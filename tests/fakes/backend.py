"""Fake Backend protocol implementation for testing."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from profitdll_wrapper._bindings.enums import (
    OK_RESULT_BY_STATE,
    ConnectionState,
    LoginResult,
)
from profitdll_wrapper._bindings.errors import NLCode
from profitdll_wrapper._bindings.structures import (
    SystemTime,
    TConnectorAssetIdentifier,
    TConnectorCancelAllOrders,
    TConnectorCancelOrder,
    TConnectorCancelOrders,
    TConnectorOrderIdentifier,
    TConnectorOrderOut,
    TConnectorPriceGroup,
    TConnectorSendOrder,
    TConnectorTrade,
    TConnectorTradingAccountPosition,
)
from profitdll_wrapper._types.models import Account


class FakeProfitBackend:
    """Fake Backend implementation for unit and integration testing."""

    def __init__(self) -> None:
        self.initialize_calls: list[str] = []
        self.subscribed: list[tuple[str, str]] = []
        self.unsubscribed: list[tuple[str, str]] = []
        self.subscribed_depth: list[tuple[str, str]] = []
        self.unsubscribed_depth: list[tuple[str, str]] = []
        self.orders_sent: list[tuple[str, int, float, int]] = []
        self.changed_orders: list[tuple[int, float, float, int]] = []
        self.cancelled_orders: list[int] = []
        self.zeroed_positions: list[tuple[str, str, str, float, int]] = []
        self.cancelled_all_ticker: list[tuple[str, str]] = []
        self.cancelled_all_account: list[str] = []
        # Espelho completo das chamadas de roteamento (senha/Version/StopPrice
        # etc.) para asserções de regressão de ABI/credenciais.
        self.routing_calls: list[dict[str, Any]] = []
        # Ordens a enumerar em enumerate_all_orders (histórico de ordens).
        self.mock_history_orders: list[Any] = []
        self.finalized: bool = False
        self.set_trade_cb_calls: int = 0
        self.set_price_depth_cb_calls: int = 0
        self._next_order_id: int = 1000

        # Callbacks capturados em initialize_* / set_*.
        self.state_callback: Any = None
        self.trade_callback: Any = None
        self.daily_callback: Any = None
        self.progress_callback: Any = None
        self.price_depth_callback: Any = None
        self.order_change_callback: Any = None
        self.order_callback: Any = None
        self.position_list_callback: Any = None
        self.trading_message_callback: Any = None
        self.asset_list_info_callback: Any = None
        self.change_state_ticker_callback: Any = None
        self.health_callback: Any = None
        self.history_trade_callback: Any = None
        self.adjust_history_callback: Any = None
        self.invalid_ticker_callback: Any = None
        self._health_status: int = 0
        self.enabled_hist_order: bool | None = None
        self._last_close_prices: dict[tuple[str, str, int], float] = {}
        self.requested_ticker_info: list[tuple[str, str]] = []
        self.history_trade_requests: list[tuple[str, str, str, str]] = []
        self.subscribed_adjust_history: list[tuple[str, str]] = []

        # Dados pendentes a materializar nos accessors.
        self._pending_trades: dict[int, TConnectorTrade] = {}
        # Price groups por (ticker, side, position) -> TConnectorPriceGroup.
        self._price_groups: dict[tuple[str, int, int], TConnectorPriceGroup] = {}
        # Contagem de níveis por (ticker, side).
        self._price_side_counts: dict[tuple[str, int], int] = {}
        # Preço teórico por ticker (ou None).
        self._theoretical_prices: dict[str, tuple[float, int]] = {}
        # Posições por (ticker, account_id) -> TConnectorTradingAccountPosition.
        self._positions: dict[tuple[str, str], TConnectorTradingAccountPosition] = {}
        # Order details by LocalOrderID -> TConnectorOrderOut (for GetOrderDetails fake).
        self._order_details: dict[int, TConnectorOrderOut] = {}
        # Nomes de agentes por (agent_id, short_flag) -> str.
        self._agent_names: dict[tuple[int, int], str] = {
            (8, 1): "UBS",
            (8, 0): "UBS Corretora",
            (120, 1): "XP",
            (120, 0): "XP Investimentos",
            (3, 1): "Simulador",
            (3, 0): "Simulador Nelogica",
            (15003, 1): "Simulador",
            (15003, 0): "Simulador Nelogica",
        }
        # Contas de teste para GetAccounts / GetAccountDetails.
        self._mock_accounts: list[Account] = []

        # Comportamento configurável.
        self.login_result: int = int(LoginResult.CONNECTED)
        self.connect_states: frozenset[ConnectionState] = frozenset()
        self.connect_delay: float = 0.0
        self.subscribe_result: int = int(NLCode.OK)
        self.initialize_result: int = int(NLCode.OK)
        self.translate_trade_result: int = int(NLCode.OK)
        self.get_price_group_result: int = int(NLCode.OK)
        self.get_theoretical_result: int = int(NLCode.OK)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Helpers de teste (não fazem parte do Protocol, mas facilitam a fixture)
    # ------------------------------------------------------------------ #
    def queue_trade(self, trade: TConnectorTrade) -> None:
        """Agenda um trade para ser materializado por ``translate_trade``."""
        with self._lock:
            self._pending_trades[int(trade.TradeNumber)] = trade

    def queue_price_group(
        self, ticker: str, side: int, position: int, group: TConnectorPriceGroup
    ) -> None:
        """Agenda um nível de book para ser lido por ``get_price_group``."""
        with self._lock:
            self._price_groups[(ticker, side, position)] = group

    def set_price_side_count(self, ticker: str, side: int, count: int) -> None:
        """Define a contagem de níveis de um lado (para ``get_price_depth_side_count``)."""
        with self._lock:
            self._price_side_counts[(ticker, side)] = count

    def set_theoretical_price(self, ticker: str, price: float, qty: int = 0) -> None:
        """Define o preço teórico de um ticker (para ``get_theoretical_values``)."""
        with self._lock:
            self._theoretical_prices[ticker] = (price, qty)

    def emit_state(self, state: ConnectionState, result: int) -> None:
        """Invoca o callback de estado capturado (simula o servidor da DLL)."""
        if self.state_callback is not None:
            self.state_callback(int(state), result)

    def emit_price_depth(
        self, asset: TConnectorAssetIdentifier, side: int, position: int, update_type: int
    ) -> None:
        """Dispara o callback de price depth (como a DLL faria)."""
        if self.price_depth_callback is not None:
            self.price_depth_callback(asset, side, position, update_type)

    def emit_daily(self, *args: object) -> None:
        """Dispara o callback de daily (args = 19 campos, conforme vendor)."""
        if self.daily_callback is not None:
            self.daily_callback(*args)

    def _emit_connect_states(self) -> None:
        """Emite estados "OK" para os domínios configurados (após initialize)."""
        if self.connect_delay > 0:
            threading.Event().wait(self.connect_delay)
        for state in self.connect_states:
            self.emit_state(state, OK_RESULT_BY_STATE[state])

    # ------------------------------------------------------------------ #
    # Implementação do Protocol Backend
    # ------------------------------------------------------------------ #
    def initialize_login(
        self,
        activation_key: str,
        user: str,
        password: str,
        state_callback: object,
        daily_callback: object,
        order_change_callback: object = None,
        progress_callback: object = None,
    ) -> int:
        self.initialize_calls.append("routing")
        self.state_callback = state_callback
        self.daily_callback = daily_callback
        if order_change_callback is not None:
            self.order_change_callback = order_change_callback
        if progress_callback is not None:
            self.progress_callback = progress_callback
        if self.initialize_result == int(NLCode.OK):
            self._emit_connect_states()
        return self.initialize_result

    def initialize_market_login(
        self,
        activation_key: str,
        user: str,
        password: str,
        state_callback: object,
        daily_callback: object,
        progress_callback: object = None,
    ) -> int:
        self.initialize_calls.append("market_data")
        self.state_callback = state_callback
        self.daily_callback = daily_callback
        if progress_callback is not None:
            self.progress_callback = progress_callback
        if self.initialize_result == int(NLCode.OK):
            self._emit_connect_states()
        return self.initialize_result

    def finalize(self) -> int:
        self.finalized = True
        return int(NLCode.OK)

    def subscribe_ticker(self, ticker: str, exchange: str) -> int:
        self.subscribed.append((ticker, exchange))
        return self.subscribe_result

    def unsubscribe_ticker(self, ticker: str, exchange: str) -> int:
        self.unsubscribed.append((ticker, exchange))
        return int(NLCode.OK)

    def set_trade_callback_v2(self, callback: object) -> int:
        self.set_trade_cb_calls += 1
        self.trade_callback = callback
        return int(NLCode.OK)

    def translate_trade(self, p_trade: int, out_trade: TConnectorTrade) -> int:
        if self.translate_trade_result != int(NLCode.OK):
            return self.translate_trade_result
        # No fake, p_trade é o TradeNumber (convenção de teste).
        with self._lock:
            src = self._pending_trades.pop(int(p_trade), None)
        if src is None:
            out_trade.Version = 0
            return int(NLCode.OK)
        out_trade.Version = src.Version
        out_trade.TradeNumber = src.TradeNumber
        out_trade.Price = src.Price
        out_trade.Quantity = src.Quantity
        out_trade.Volume = src.Volume
        out_trade.BuyAgent = src.BuyAgent
        out_trade.SellAgent = src.SellAgent
        out_trade.TradeType = src.TradeType
        out_trade.TradeDate = src.TradeDate
        return int(NLCode.OK)

    # ---- Price Depth (P1) ---- #
    def subscribe_price_depth(self, asset: TConnectorAssetIdentifier) -> int:
        self.subscribed_depth.append((str(asset.Ticker), str(asset.Exchange)))
        return self.subscribe_result

    def unsubscribe_price_depth(self, asset: TConnectorAssetIdentifier) -> int:
        self.unsubscribed_depth.append((str(asset.Ticker), str(asset.Exchange)))
        return int(NLCode.OK)

    def set_price_depth_callback(self, callback: object) -> int:
        self.set_price_depth_cb_calls += 1
        self.price_depth_callback = callback
        return int(NLCode.OK)

    def set_offer_book_callback_v2(self, callback: object) -> int:
        self.offer_book_callback = callback
        return int(NLCode.OK)

    def subscribe_offer_book(self, ticker: str, exchange: str) -> int:
        self.subscribed.append((ticker, exchange))
        return self.subscribe_result

    def unsubscribe_offer_book(self, ticker: str, exchange: str) -> int:
        self.unsubscribed.append((ticker, exchange))
        return int(NLCode.OK)

    def get_price_depth_side_count(self, asset: TConnectorAssetIdentifier, side: int) -> int:
        with self._lock:
            return self._price_side_counts.get((str(asset.Ticker), side), 0)

    def get_price_group(
        self,
        asset: TConnectorAssetIdentifier,
        side: int,
        position: int,
        out_group: TConnectorPriceGroup,
    ) -> int:
        if self.get_price_group_result != int(NLCode.OK):
            return self.get_price_group_result
        with self._lock:
            src = self._price_groups.get((str(asset.Ticker), side, position))
        if src is None:
            out_group.Version = 0
            return int(NLCode.OK)
        out_group.Version = src.Version
        out_group.Price = src.Price
        out_group.Count = src.Count
        out_group.Quantity = src.Quantity
        out_group.PriceGroupFlags = src.PriceGroupFlags
        return int(NLCode.OK)

    def get_theoretical_values(
        self,
        asset: TConnectorAssetIdentifier,
        out_price: Any,
        out_qty: Any,
    ) -> int:
        if self.get_theoretical_result != int(NLCode.OK):
            return self.get_theoretical_result
        with self._lock:
            pair = self._theoretical_prices.get(str(asset.Ticker))
        if pair is None:
            out_price.value = float("-inf")
            out_qty.value = 0
            return int(NLCode.OK)
        out_price.value = pair[0]
        out_qty.value = pair[1]
        return int(NLCode.OK)

    # ---- Routing & Ordens (P2) ---- #
    def send_order(self, order: TConnectorSendOrder, out_id: Any) -> int:
        if self.subscribe_result != int(NLCode.OK):
            return self.subscribe_result
        with self._lock:
            self._next_order_id += 1
            out_id.value = self._next_order_id
            self.orders_sent.append(
                (
                    str(order.AssetID.Ticker),
                    int(order.OrderSide),
                    float(order.Price),
                    int(order.Quantity),
                )
            )
            self.routing_calls.append(
                {
                    "method": "send_order",
                    "password": str(order.Password or ""),
                    "version": int(order.Version),
                    "stop_price": float(order.StopPrice),
                    "order_type": int(order.OrderType),
                    "order_side": int(order.OrderSide),
                    "message_id": int(order.MessageID),
                }
            )
        return int(NLCode.OK)

    def send_change_order_v2(self, change: Any) -> int:
        if self.subscribe_result != int(NLCode.OK):
            return self.subscribe_result
        with self._lock:
            order_id = int(change.OrderID.LocalOrderID)
            price = float(change.Price)
            stop_price = float(change.StopPrice)
            quantity = int(change.Quantity)
            self.changed_orders.append((order_id, price, stop_price, quantity))
            self.routing_calls.append(
                {
                    "method": "send_change_order_v2",
                    "password": str(change.Password or ""),
                    "version": int(change.Version),
                    "stop_price": stop_price,
                }
            )
        return int(NLCode.OK)

    def send_cancel_order_v2(self, cancel: TConnectorCancelOrder) -> int:
        with self._lock:
            self.cancelled_orders.append(int(cancel.OrderID.LocalOrderID))
            self.routing_calls.append(
                {
                    "method": "send_cancel_order_v2",
                    "password": str(cancel.Password or ""),
                    "version": int(cancel.Version),
                }
            )
        return int(NLCode.OK)

    def send_cancel_orders_v2(self, cancel: TConnectorCancelOrders) -> int:
        with self._lock:
            self.cancelled_all_ticker.append(
                (str(cancel.AssetID.Ticker), str(cancel.AssetID.Exchange))
            )
            self.routing_calls.append(
                {
                    "method": "send_cancel_orders_v2",
                    "password": str(cancel.Password or ""),
                    "version": int(cancel.Version),
                }
            )
        return int(NLCode.OK)

    def send_cancel_all_orders(self, cancel: TConnectorCancelAllOrders) -> int:
        with self._lock:
            self.cancelled_all_account.append(str(cancel.AccountID.AccountID))
            self.routing_calls.append(
                {
                    "method": "send_cancel_all_orders",
                    "password": str(cancel.Password or ""),
                    "version": int(cancel.Version),
                }
            )
        return int(NLCode.OK)

    def send_zero_position_v2(self, zero: Any, out_id: Any) -> int:
        if self.subscribe_result != int(NLCode.OK):
            return self.subscribe_result
        with self._lock:
            self._next_order_id += 1
            out_id.value = self._next_order_id
            ticker = str(zero.AssetID.Ticker)
            exchange = str(zero.AssetID.Exchange)
            account = str(zero.AccountID.AccountID)
            price = float(zero.Price)
            pos_type = int(zero.PositionType)
            self.zeroed_positions.append((ticker, exchange, account, price, pos_type))
            self.routing_calls.append(
                {
                    "method": "send_zero_position_v2",
                    "password": str(zero.Password or ""),
                    "version": int(zero.Version),
                    "price": price,
                    "position_type": pos_type,
                }
            )
        return int(NLCode.OK)

    def get_position_v2(
        self,
        out_pos: TConnectorTradingAccountPosition,
    ) -> int:
        with self._lock:
            if getattr(self, "position_error_code", int(NLCode.OK)) != int(NLCode.OK):
                return int(self.position_error_code)
            key = (str(out_pos.AssetID.Ticker or ""), str(out_pos.AccountID.AccountID or ""))
            src = self._positions.get(key)
        if src is not None:
            out_pos.Version = src.Version
            out_pos.DailyQuantity = src.DailyQuantity
            out_pos.OpenAveragePrice = src.OpenAveragePrice
            out_pos.DailyBuyQuantity = src.DailyBuyQuantity
            out_pos.DailySellQuantity = src.DailySellQuantity
            out_pos.DailyAverageBuyPrice = src.DailyAverageBuyPrice
            out_pos.DailyAverageSellPrice = src.DailyAverageSellPrice
        else:
            out_pos.Version = 0
            out_pos.DailyQuantity = 0
            out_pos.OpenAveragePrice = 0.0
        return int(NLCode.OK)

    def set_order_change_callback_v2(self, callback: object) -> int:
        self.order_change_callback = callback
        return int(NLCode.OK)

    def set_order_callback(self, callback: object) -> int:
        self.order_callback = callback
        return int(NLCode.OK)

    def set_order_history_callback(self, callback: object) -> int:
        self.order_history_callback = callback
        return int(NLCode.OK)

    def get_order_details(self, order_out: TConnectorOrderOut) -> int:
        with self._lock:
            src = self._order_details.get(int(order_out.OrderID.LocalOrderID))
        if src is None:
            return int(NLCode.NOT_FOUND)
        # Copy relevant fields to order_out
        order_out.Quantity = src.Quantity
        order_out.TradedQuantity = src.TradedQuantity
        order_out.LeavesQuantity = src.LeavesQuantity
        order_out.Price = src.Price
        order_out.StopPrice = src.StopPrice
        order_out.AveragePrice = src.AveragePrice
        order_out.OrderSide = src.OrderSide
        order_out.OrderType = src.OrderType
        order_out.OrderStatus = src.OrderStatus
        order_out.ValidityType = src.ValidityType
        order_out.TextMessageLength = src.TextMessageLength
        order_out.AssetID.TickerLength = src.AssetID.TickerLength
        order_out.AssetID.ExchangeLength = src.AssetID.ExchangeLength
        if src.AssetID.Ticker:
            order_out.AssetID.Ticker = src.AssetID.Ticker
        if src.AssetID.Exchange:
            order_out.AssetID.Exchange = src.AssetID.Exchange
        if src.AccountID.AccountID:
            order_out.AccountID.AccountID = src.AccountID.AccountID
        if src.TextMessage:
            order_out.TextMessage = src.TextMessage
        return int(NLCode.OK)

    def set_asset_position_list_callback(self, callback: object) -> int:
        self.position_list_callback = callback
        return int(NLCode.OK)

    def set_trading_message_result_callback(self, callback: object) -> int:
        self.trading_message_callback = callback
        return int(NLCode.OK)

    def request_ticker_info(self, ticker: str, exchange: str) -> int:
        with self._lock:
            self.requested_ticker_info.append((ticker, exchange))
        return int(NLCode.OK)

    def set_asset_list_info_callback_v2(self, callback: object) -> int:
        self.asset_list_info_callback = callback
        return int(NLCode.OK)

    def set_change_state_ticker_callback(self, callback: object) -> int:
        self.change_state_ticker_callback = callback
        return int(NLCode.OK)

    # ---- Contas & Enumerações ---- #
    def get_account_count(self) -> int:
        with self._lock:
            masters = [a for a in self._mock_accounts if not a.sub_account_id]
            return len(masters)

    def get_accounts(
        self, start_source: int, start_dest: int, count: int, accounts_out: Any
    ) -> int:
        with self._lock:
            masters = [a for a in self._mock_accounts if not a.sub_account_id]
            written = 0
            for i in range(min(count, len(masters))):
                acc = masters[i]
                accounts_out[i].Version = 0
                accounts_out[i].BrokerID = acc.broker_id
                accounts_out[i].AccountID = acc.account_id
                written += 1
            return written

    def get_account_details(self, account_out: Any) -> int:
        with self._lock:
            acc_id = str(account_out.AccountID.AccountID or "")
            sub_id = str(account_out.AccountID.SubAccountID or "")
            found = None
            for a in self._mock_accounts:
                if a.account_id == acc_id and a.sub_account_id == sub_id:
                    found = a
                    break

            if found is None:
                return int(NLCode.NOT_FOUND)

            account_out.BrokerNameLength = len(found.broker_name)
            account_out.OwnerNameLength = len(found.owner_name)
            account_out.SubOwnerNameLength = len(found.sub_owner_name)
            account_out.AccountFlags = found.account_flags
            account_out.AccountType = found.account_type

            if getattr(account_out, "BrokerName", None):
                account_out.BrokerName = found.broker_name
            if getattr(account_out, "OwnerName", None):
                account_out.OwnerName = found.owner_name
            if getattr(account_out, "SubOwnerName", None):
                account_out.SubOwnerName = found.sub_owner_name

            return int(NLCode.OK)

    def get_sub_account_count(self, master_id: Any) -> int:
        with self._lock:
            master_acc = str(master_id.AccountID or "")
            subs = [
                a for a in self._mock_accounts if a.account_id == master_acc and a.sub_account_id
            ]
            return len(subs)

    def get_sub_accounts(
        self, master_id: Any, start_source: int, start_dest: int, count: int, accounts_out: Any
    ) -> int:
        with self._lock:
            master_acc = str(master_id.AccountID or "")
            subs = [
                a for a in self._mock_accounts if a.account_id == master_acc and a.sub_account_id
            ]
            written = 0
            for i in range(min(count, len(subs))):
                sub = subs[i]
                accounts_out[i].Version = 0
                accounts_out[i].BrokerID = sub.broker_id
                accounts_out[i].AccountID = sub.account_id
                accounts_out[i].SubAccountID = sub.sub_account_id
                written += 1
            return written

    def get_account_count_by_broker(self, broker_id: int) -> int:
        return 0

    def get_accounts_by_broker(
        self, broker_id: int, start_source: int, start_dest: int, count: int, accounts_out: Any
    ) -> int:
        return int(NLCode.OK)

    def has_orders_in_interval(self, account_id: Any, start: Any, end: Any) -> int:
        return int(NLCode.OK)

    def enumerate_orders_by_interval(
        self,
        account_id: Any,
        order_version: int,
        start: Any,
        end: Any,
        param: int,
        callback: object,
    ) -> int:
        return int(NLCode.OK)

    def enumerate_all_orders(
        self, account_id: Any, order_version: int, param: int, callback: object
    ) -> int:
        from ctypes import pointer

        with self._lock:
            orders = list(self.mock_history_orders)
        for order in orders:
            callback(pointer(order), param)
        return int(NLCode.OK)

    def enumerate_all_position_assets(
        self, account_id: Any, asset_version: int, param: int, callback: object
    ) -> int:
        return int(NLCode.OK)

    def get_agent_name_length(self, agent_id: int, short_flag: int) -> int:
        with self._lock:
            name = self._agent_names.get((agent_id, short_flag), "")
            return len(name)

    def get_agent_name(self, count: int, agent_id: int, pwc_agent: Any, short_flag: int) -> int:
        with self._lock:
            name = self._agent_names.get((agent_id, short_flag), "")
            if not name:
                return int(NLCode.NOT_FOUND)
            pwc_agent.value = name
            return len(name)

    def set_day_trade(self, use_day_trade: int) -> int:
        return int(NLCode.OK)

    def set_enabled_log_to_debug(self, enabled: int) -> int:
        return int(NLCode.OK)

    def get_server_clock(
        self,
        dt_date: Any,
        year: Any,
        month: Any,
        day: Any,
        hour: Any,
        minute: Any,
        sec: Any,
        millisec: Any,
    ) -> int:
        return int(NLCode.OK)

    def emit_order_change_v2(self, *args: Any) -> None:
        """Dispara o callback de order change V2 em testes (deprecated)."""
        if self.order_change_callback is not None:
            self.order_change_callback(*args)

    def emit_order_callback(self, order_id: TConnectorOrderIdentifier) -> None:
        """Dispara o callback de ordem V1 em testes."""
        if self.order_callback is not None:
            self.order_callback(order_id)

    def set_mock_position(
        self, ticker: str, account_id: str, pos: TConnectorTradingAccountPosition
    ) -> None:
        """Agenda uma posição para ser retornada por get_position_v2."""
        with self._lock:
            self._positions[(ticker, account_id)] = pos

    def set_mock_order_details(self, local_order_id: int, order_out: TConnectorOrderOut) -> None:
        """Agenda detalhes de ordem para ser retornado por get_order_details."""
        with self._lock:
            self._order_details[local_order_id] = order_out

    def emit_trading_message(self, res: Any) -> None:
        """Dispara o callback de mensagem de negociação/risco em testes."""
        if self.trading_message_callback is not None:
            from ctypes import pointer

            self.trading_message_callback(pointer(res))

    def emit_asset_info(
        self,
        r_asset: Any,
        name: str = "",
        description: str = "",
        min_qty: int = 1,
        max_qty: int = 1000000,
        lot: int = 100,
        sec_type: int = 1,
        sub_type: int = 0,
        min_inc: float = 0.01,
        mult: float = 1.0,
        valid_date: str = "",
        isin: str = "",
        sector: str = "",
        subsector: str = "",
        segment: str = "",
    ) -> None:
        """Dispara o callback de asset list info V2 em testes."""
        if self.asset_list_info_callback is not None:
            self.asset_list_info_callback(
                r_asset,
                name,
                description,
                min_qty,
                max_qty,
                lot,
                sec_type,
                sub_type,
                min_inc,
                mult,
                valid_date,
                isin,
                sector,
                subsector,
                segment,
            )

    def emit_change_state_ticker(self, r_asset: Any, date: str, state: int) -> None:
        """Dispara o callback de mudança de estado do ativo em testes."""
        if self.change_state_ticker_callback is not None:
            self.change_state_ticker_callback(r_asset, date, state)

    def get_health_status(self, out_state: Any) -> int:
        with self._lock:
            if hasattr(out_state, "contents"):
                out_state.contents.value = self._health_status
            else:
                out_state._obj.value = self._health_status
        return int(NLCode.OK)

    def set_health_callback(self, callback: object) -> int:
        with self._lock:
            self.health_callback = callback
        return int(NLCode.OK)

    def emit_health_change(self, state: int) -> None:
        """Dispara o callback de alteração de integridade em testes."""
        with self._lock:
            self._health_status = state
            cb = self.health_callback
        if cb is not None:
            cb(state)

    def set_mock_accounts(self, accounts: list[Account]) -> None:
        """Agenda contas para serem retornadas por get_accounts/get_account_details."""
        with self._lock:
            self._mock_accounts = list(accounts)

    def set_enabled_hist_order(self, enabled: int) -> int:
        with self._lock:
            self.enabled_hist_order = bool(enabled)
        return int(NLCode.OK)

    def set_history_trade_callback_v2(self, callback: object) -> int:
        with self._lock:
            self.history_trade_callback = callback
        return int(NLCode.OK)

    def set_serie_progress_callback(self, callback: object) -> int:
        with self._lock:
            self.progress_callback = callback if callback is not None else None
        return int(NLCode.OK)

    def get_history_trades(self, ticker: str, exchange: str, start: str, end: str) -> int:
        with self._lock:
            self.history_trade_requests.append((ticker, exchange, start, end))
        return int(NLCode.OK)

    def set_last_daily_close(
        self, ticker: str, exchange: str, close_price: float, adjusted: bool = True
    ) -> None:
        with self._lock:
            self._last_close_prices[(ticker, exchange, 1 if adjusted else 0)] = close_price

    def get_last_daily_close(
        self, ticker: str, exchange: str, out_close: Any, adjusted: int
    ) -> int:
        with self._lock:
            val = self._last_close_prices.get((ticker, exchange, adjusted), 100.0)
            if hasattr(out_close, "contents"):
                out_close.contents.value = val
            else:
                out_close._obj.value = val
        return int(NLCode.OK)

    def emit_history_trade(
        self,
        asset_id: Any,
        date: str,
        price: float,
        qty: int,
        side: int = 1,
        trade_id: int = 1,
        flags: int = 0,
        when: datetime | None = None,
    ) -> None:
        """Emits a historical trade via history_trade_callback in tests.

        ``when`` overrides the trade timestamp (naive B3 local) so window
        filtering can be exercised deterministically; defaults to now().
        """
        now = when or datetime.now()
        raw = TConnectorTrade()
        raw.Version = 0
        raw.TradeNumber = trade_id
        raw.Price = price
        raw.Quantity = qty
        raw.TradeType = side
        raw.TradeDate = SystemTime(
            wYear=now.year,
            wMonth=now.month,
            wDayOfWeek=now.weekday(),
            wDay=now.day,
            wHour=now.hour,
            wMinute=now.minute,
            wSecond=now.second,
            wMilliseconds=now.microsecond // 1000,
        )

        with self._lock:
            self._pending_trades[trade_id] = raw
            cb = self.history_trade_callback

        if cb is not None:
            cb(asset_id, trade_id, flags)

    def emit_history_progress(self, ticker: str, exchange: str, progress: int) -> None:
        """Dispara o callback de progresso (TProgressCallback) em testes."""
        from ctypes import c_wchar_p

        from profitdll_wrapper._bindings.structures import TAssetID

        raw = TAssetID()
        raw.ticker = c_wchar_p(ticker)
        raw.bolsa = c_wchar_p(exchange)

        with self._lock:
            cb = self.progress_callback
        if cb is not None:
            cb(raw, progress)

    def subscribe_adjust_history(self, ticker: str, exchange: str) -> int:
        with self._lock:
            self.subscribed_adjust_history.append((ticker, exchange))
        return int(NLCode.OK)

    def unsubscribe_adjust_history(self, ticker: str, exchange: str) -> int:
        with self._lock:
            if (ticker, exchange) in self.subscribed_adjust_history:
                self.subscribed_adjust_history.remove((ticker, exchange))
        return int(NLCode.OK)

    def set_adjust_history_callback_v2(self, callback: object) -> int:
        with self._lock:
            self.adjust_history_callback = callback
        return int(NLCode.OK)

    def set_invalid_ticker_callback(self, callback: object) -> int:
        with self._lock:
            self.invalid_ticker_callback = callback
        return int(NLCode.OK)

    def emit_adjust_history(
        self,
        asset_id: Any,
        value: float,
        adjust_type: str = "DIVIDENDO",
        observation: str = "",
        adjust_date: str = "01/08/2026",
        deliberation_date: str = "01/08/2026",
        payment_date: str = "15/08/2026",
        affect_price: bool = True,
    ) -> None:
        """Emite uma notificação de provento/ajuste via adjust_history_callback em testes."""
        from ctypes import c_wchar_p

        from profitdll_wrapper._bindings.structures import TAssetID

        ticker_str = getattr(asset_id, "ticker", str(asset_id)) or "PETR4"
        bolsa_str = getattr(asset_id, "exchange", getattr(asset_id, "bolsa", "B")) or "B"

        t_ptr = c_wchar_p(ticker_str)
        b_ptr = c_wchar_p(bolsa_str)

        raw = TAssetID()
        raw.ticker = t_ptr
        raw.bolsa = b_ptr

        with self._lock:
            cb = self.adjust_history_callback
        if cb is not None:
            cb(
                raw,
                value,
                adjust_type,
                observation,
                adjust_date,
                deliberation_date,
                payment_date,
                1 if affect_price else 0,
            )

    def emit_invalid_ticker(self, ticker: str, exchange: str = "B") -> None:
        """Emite uma notificação de ativo/bolsa inválido via invalid_ticker_callback em testes."""
        from ctypes import pointer

        from profitdll_wrapper._bindings.structures import TConnectorAssetIdentifier

        asset = TConnectorAssetIdentifier()
        asset.Version = 0
        asset.Ticker = ticker
        asset.Exchange = exchange

        with self._lock:
            cb = self.invalid_ticker_callback
        if cb is not None:
            cb(pointer(asset))


__all__ = ["FakeProfitBackend"]
