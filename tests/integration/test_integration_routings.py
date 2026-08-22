"""Integration tests for routing and order placement against the real profitdll_wrapper binary and the Nelogica simulator server.

Migration of the legacy scripts into the formal pytest suite.
Run only on Windows with the profitdll_wrapper located and credentials in .env.
"""

from __future__ import annotations

import threading
import time

import pytest

from profitdll_wrapper import Event, Order, ProfitClient
from tests.integration.conftest import (
    require_dll_and_credentials,
    skip_on_live_infra_error,
)


@pytest.mark.integration
class TestRealDLLRoutingIntegration:
    def test_real_dll_routing_connection(self, simulator_env: dict[str, str]) -> None:
        require_dll_and_credentials(simulator_env)

        from profitdll_wrapper._bindings.functions import get_backend

        backend = get_backend()
        assert backend is not None

        key = simulator_env["ACTIVATION_KEY"]
        user = simulator_env["USER"]
        password = simulator_env["PASSWORD"]

        try:
            with ProfitClient(
                activation_key=key,
                user=user,
                password=password,
                mode="routing",
                backend=backend,
            ) as client:
                assert client.is_connected

                # Query accounts/positions.
                accounts = client.get_accounts()
                assert isinstance(accounts, list)
        except BaseException as exc:
            # Only connection/auth failures (external infra) become skips.
            skip_on_live_infra_error(exc, context="Live routing connection unavailable")

    def test_real_dll_order_placement_and_cancel(self, simulator_env: dict[str, str]) -> None:
        require_dll_and_credentials(simulator_env)

        from profitdll_wrapper._bindings.functions import get_backend

        backend = get_backend()
        assert backend is not None

        key = simulator_env["ACTIVATION_KEY"]
        user = simulator_env["USER"]
        password = simulator_env["PASSWORD"]
        account_id = simulator_env.get("ACCOUNT_ID", "")
        broker_str = simulator_env.get("BROKER", "15003")
        broker_id = int(broker_str) if broker_str.isdigit() else 15003

        if not account_id:
            pytest.skip("ACCOUNT_ID missing from .env")

        orders_received: list[Order] = []
        order_event = threading.Event()

        try:
            with ProfitClient(
                activation_key=key,
                user=user,
                password=password,
                mode="routing",
                backend=backend,
            ) as client:
                assert client.is_connected

                @client.on(Event.ORDER)
                def on_order(order: Order) -> None:
                    orders_received.append(order)
                    order_event.set()

                # Submit a far-away limit order to cancel it right after.
                order_id = client.send_buy_order(
                    "WDOFUT",
                    exchange="F",
                    account=account_id,
                    password=password,
                    broker_id=broker_id,
                    price=1000.0,
                    quantity=1,
                )

                assert isinstance(order_id, (int, str))
                # Wait for the order callback (up to 5s) instead of a fixed sleep.
                if not order_event.wait(timeout=5.0):
                    # Callback did not arrive, but the order may still have been
                    # accepted; proceed to cancel regardless.
                    pass

                # Cancel all orders on the test account.
                client.cancel_all_account_orders(
                    account=account_id,
                    password=password,
                    broker_id=broker_id,
                )
                # Allow the cancel acknowledgement callback to drain.
                time.sleep(1.0)

            assert not client.is_connected
        except BaseException as exc:
            # Only connection/auth failures (external infra) become skips.
            skip_on_live_infra_error(exc, context="Live routing connection unavailable")
