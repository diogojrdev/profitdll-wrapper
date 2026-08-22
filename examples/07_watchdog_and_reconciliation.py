"""Process Health Watchdog & Position / Order Reconciliation example.

Demonstrates:
  1. Native DLL thread health monitoring (`get_health_status()`, `Event.HEALTH_CHANGE`);
  2. Connection state monitoring and auto-resubscription (`resubscribe_all`);
  3. Active initial and periodic reconciliation of orders and custody positions (`get_all_positions`, `get_accounts`);
  4. Handling broker risk messages and order rejection notifications (`Event.TRADING_MESSAGE`).

Execution:
    uv run python examples/07_watchdog_and_reconciliation.py
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from _common import load_credentials, setup_dll_path
from profitdll_wrapper import (
    Account,
    Event,
    Position,
    ProfitClient,
    SystemHealthState,
    TradingMessageResult,
)

setup_dll_path()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("watchdog_reconciler")


class HealthWatchdogAndReconciler:
    """Monitors native DLL thread responsiveness and reconciles custody positions."""

    def __init__(self, client: ProfitClient, account: str) -> None:
        self.client = client
        self.account = account
        self.is_healthy = True

    def setup(self) -> None:
        self._register_watchdog()
        self._register_reconciliation()

    def _register_watchdog(self) -> None:
        @self.client.on(Event.HEALTH_CHANGE)
        def on_health_change(state: SystemHealthState) -> None:
            if state == SystemHealthState.RESPONSIVE:
                logger.info("WATCHDOG: Native DLL threads responding normally (RESPONSIVE).")
                self.is_healthy = True
            else:
                logger.critical("WATCHDOG CRITICAL ALERT: Native DLL thread STALLED / FROZEN! Emergency action recommended.")
                self.is_healthy = False

        @self.client.on(Event.STATE)
        def on_connection_state(state_data: Any) -> None:
            logger.info("CONNECTION STATE CHANGED: %s", state_data)

        @self.client.on(Event.TRADING_MESSAGE)
        def on_trading_message(msg: TradingMessageResult) -> None:
            logger.warning(
                "RISK / REJECTION MESSAGE: Code=%s | Local Order ID=%d | ClOrdID=%s | Msg='%s'",
                msg.result_code,
                msg.local_order_id,
                msg.cl_ord_id,
                msg.message,
            )

    def _register_reconciliation(self) -> None:
        @self.client.on(Event.POSITION)
        def on_position_update(pos: Position) -> None:
            logger.info(
                "RECONCILIATION EVENT -> Position in %s: Qty=%d | Avg Price=%.2f",
                pos.asset.ticker, pos.quantity, pos.average_price
            )

    def run_reconciliation(self, ticker: str = "PETR4", exchange: str = "B") -> None:
        """Executes explicit reconciliation sweep of accounts and custody positions."""
        logger.info("--- STARTING CUSTODY & ORDER RECONCILIATION SWEEP ---")
        try:
            accounts: list[Account] = self.client.get_accounts()
            logger.info("Accounts reported by DLL (%d):", len(accounts))
            for acc in accounts:
                logger.info(
                    "   -> Name: %s | ID: %s | Broker: %s",
                    acc.owner_name or acc.account_id,
                    acc.account_id,
                    acc.broker_name or acc.broker_id,
                )

            pos: Position = self.client.get_position(ticker=ticker, exchange=exchange, account=self.account)
            logger.info(
                "Custody Position for %s (%s): Qty=%d | Avg Price=%.2f | Day Buy=%d | Day Sell=%d",
                pos.asset.ticker, pos.asset.exchange, pos.quantity, pos.average_price, pos.buy_quantity, pos.sell_quantity
            )

            current_health = self.client.get_health_status()
            logger.info("Direct Health Query Status: %s", current_health.name)

        except Exception as exc:
            logger.error("Error during reconciliation sweep: %s", exc)

    def test_auto_resubscribe(self) -> None:
        """Demonstrates restoring active ticker subscriptions."""
        logger.info("Testing subscription restoration via resubscribe_all()...")
        restored = self.client.resubscribe_all()
        logger.info("Total subscriptions restored: %d", restored)


def main() -> int:
    key, user, password, account = load_credentials()
    if not (key and user and password):
        logger.error("Missing credentials. Please set PROFITDLL_ACTIVATION_KEY, PROFITDLL_USER, and PROFITDLL_PASSWORD in .env")
        return 2

    ticker = os.environ.get("WATCHDOG_TICKER", "PETR4")
    exchange = os.environ.get("WATCHDOG_EXCHANGE", "B")

    logger.info("Initializing ProfitClient for Process Health Watchdog & Reconciliation...")
    try:
        with ProfitClient(
            activation_key=key,
            user=user,
            password=password,
            mode="routing",
            auto_resubscribe=True,
        ) as client:
            logger.info("Client connected successfully!")

            watchdog = HealthWatchdogAndReconciler(client=client, account=account)
            watchdog.setup()

            watchdog.run_reconciliation(ticker=ticker, exchange=exchange)

            client.subscribe(ticker, exchange=exchange)
            watchdog.test_auto_resubscribe()

            print("\n=== Process Health Watchdog & Reconciliation Active ===")
            print("Press Ctrl+C to exit.\n")

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
        logger.info("Manual shutdown requested.")
    except Exception as exc:
        logger.error("Error in watchdog/reconciler: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
