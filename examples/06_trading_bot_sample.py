"""Automated Trading Bot Template with Order & Risk Management.

Demonstrates:
  1. Connecting in 'routing' mode using context manager (`ProfitClient`);
  2. Inspecting account custody and initial positions (`get_all_positions`);
  3. Real-time tick strategy decision engine driven by market trade callbacks;
  4. Order lifecycle tracking (`send_order`, `change_order`, `cancel_order`);
  5. Risk management (Stop Loss / Take Profit logic);
  6. Emergency position zeroing and order cancellation (`zero_position`, `cancel_all_orders`).

Execution:
    uv run python examples/06_trading_bot_sample.py
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Dict

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import (
    Event,
    Order,
    OrderStatus,
    Position,
    ProfitClient,
    Trade,
)

setup_dll_path()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("trading_bot")


class BotState(Enum):
    IDLE = 0
    BUY_SENT = 1
    POSITION_OPEN = 2
    CLOSING = 3


@dataclass
class BotConfig:
    ticker: str = "PETR4"
    exchange: str = "B"  # Bovespa (B3 equities)
    quantity: int = 100  # 1 standard lot of shares on B3
    stop_loss_pts: float = 0.50
    take_profit_pts: float = 1.00
    safe_test_mode: bool = True  # If True, places limit order far from market to avoid unintentional execution


class GridTradingBot:
    """Sample trading algorithm managing order lifecycle and risk rules."""

    def __init__(self, client: ProfitClient, account: str, config: BotConfig) -> None:
        self.client = client
        self.account = account
        self.config = config
        self.state = BotState.IDLE

        self.last_price: float = 0.0
        self.entry_price: float = 0.0
        self.active_order_id: int | None = None
        self.orders: Dict[int, Order] = {}

    def start(self) -> None:
        logger.info(
            "Trading bot initialized for asset %s@%s | Account: %s",
            self.config.ticker, self.config.exchange, self.account
        )
        self._register_callbacks()
        self.client.subscribe(self.config.ticker, exchange=self.config.exchange)

    def _register_callbacks(self) -> None:
        @self.client.on(Event.TRADE)
        def on_trade(trade: Trade) -> None:
            if trade.asset.ticker == self.config.ticker:
                self.last_price = trade.price
                self._evaluate_strategy()

        @self.client.on(Event.ORDER)
        def on_order(order: Order) -> None:
            logger.info(
                "ORDER UPDATE -> ID=%s | Status=%s | Executed=%d/%d | Price=%.2f | Msg='%s'",
                order.id, order.status.name, order.traded_quantity, order.quantity, order.price, order.text_message
            )
            self.orders[order.id] = order

            if order.id == self.active_order_id:
                if order.status == OrderStatus.FILLED:
                    logger.info("Order fully executed! Entry average price: %.2f", order.average_price)
                    self.entry_price = order.average_price
                    self.state = BotState.POSITION_OPEN
                elif order.status in (OrderStatus.CANCELED, OrderStatus.REJECTED):
                    logger.warning("Order cancelled or rejected: %s", order.status.name)
                    self.state = BotState.IDLE
                    self.active_order_id = None

        @self.client.on(Event.POSITION)
        def on_position(pos: Position) -> None:
            if pos.asset.ticker == self.config.ticker:
                logger.info("POSITION UPDATE: Qty=%d | Avg Price=%.2f", pos.quantity, pos.average_price)

    def _evaluate_strategy(self) -> None:
        """Strategy decision engine."""
        if self.state == BotState.IDLE:
            if self.last_price > 0:
                logger.info("Current market price: %.2f. Triggering entry order...", self.last_price)
                self._send_entry_order()

        elif self.state == BotState.POSITION_OPEN:
            pnl_pts = self.last_price - self.entry_price
            logger.info(
                "Position open. Current PnL: %.2f pts (Current: %.2f | Entry: %.2f)",
                pnl_pts, self.last_price, self.entry_price
            )

            if pnl_pts >= self.config.take_profit_pts:
                logger.info("TAKE PROFIT target reached (%.2f pts). Closing position!", pnl_pts)
                self._close_position()
            elif pnl_pts <= -self.config.stop_loss_pts:
                logger.warning("STOP LOSS trigger reached (%.2f pts). Zeroing position!", pnl_pts)
                self._close_position()

    def _send_entry_order(self) -> None:
        target_price = self.last_price * 0.90 if self.config.safe_test_mode else self.last_price

        logger.info(
            "Submitting LIMIT BUY for %d share(s) @ $ %.2f...",
            self.config.quantity, target_price
        )
        try:
            # The routing password configured on the client is used automatically.
            order_id = self.client.send_buy_order(
                self.config.ticker,
                exchange=self.config.exchange,
                account=self.account,
                price=target_price,
                quantity=self.config.quantity,
            )
            self.active_order_id = order_id
            self.state = BotState.BUY_SENT
            logger.info("Order registered on server. Local order ID: %d", order_id)
        except Exception as exc:
            logger.error("Failed to submit entry order: %s", exc)

    def _close_position(self) -> None:
        self.state = BotState.CLOSING
        logger.info("Executing emergency position zeroing for %s...", self.config.ticker)
        try:
            self.client.cancel_all_orders(
                ticker=self.config.ticker,
                exchange=self.config.exchange,
                account=self.account,
            )
            self.client.zero_position(
                account=self.account,
                ticker=self.config.ticker,
                exchange=self.config.exchange,
            )
            logger.info("Position zeroing command submitted successfully.")
        except Exception as exc:
            logger.error("Error during position zeroing: %s", exc)


def main() -> int:
    key, user, password, account, routing_key = load_credentials()
    if not (key and user and password):
        logger.error("Missing credentials. Please set PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, and PROFITDLL_PASSWORD in .env")
        return 2
    if not routing_key:
        logger.error(
            "Missing ROUTING_KEY: order routing requires the routing password, "
            "which differs from the login password."
        )
        return 2

    config = BotConfig(
        ticker=os.environ.get("BOT_TICKER", "PETR4"),
        exchange=os.environ.get("BOT_EXCHANGE", "B"),
        safe_test_mode=True,
    )

    logger.info("Connecting ProfitClient in 'routing' mode...")
    try:
        with ProfitClient(
            activation_key=key,
            user=user,
            password=password,
            routing_password=routing_key,
            mode="routing",
            auto_resubscribe=True,
        ) as client:
            logger.info("Order routing connection established!")

            try:
                positions = client.get_all_positions(account=account)
                logger.info("Current custody positions for account %s: %d active positions.", account, len(positions))
                for p in positions:
                    logger.info("   -> %s: Qty=%d | Avg Price=%.2f", p.asset.ticker, p.quantity, p.average_price)
            except Exception as exc:
                logger.warning("Could not query initial custody positions: %s", exc)

            bot = GridTradingBot(client=client, account=account, config=config)
            bot.start()

            print("\n=== Automated Trading Bot Active ===")
            print("Press Ctrl+C to stop bot and cancel active orders.\n")

            if os.environ.get("CI_TIMEOUT"):
                run_time = float(os.environ["CI_TIMEOUT"])
                logger.info("Running for %.1f seconds (CI_TIMEOUT)...", run_time)
                timer = threading.Timer(run_time, client.stop)
                timer.start()
                try:
                    client.run()
                finally:
                    timer.cancel()
            else:
                client.run()

    except KeyboardInterrupt:
        logger.info("Manual shutdown requested. Cancelling active open orders...")
    except Exception as exc:
        logger.error("Fatal error during bot execution: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
