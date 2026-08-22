"""Integration tests against the real profitdll_wrapper binary and simulator server.

Run only when:
1. The OS is Windows;
2. The native profitdll_wrapper can be located by the loader;
3. The .env file contains ACTIVATION_KEY, USER, and PASSWORD.
"""

from __future__ import annotations

import threading

import pytest

from profitdll_wrapper import Event, ProfitClient, Trade
from tests.integration.conftest import (
    require_dll_and_credentials,
    skip_on_live_infra_error,
)


@pytest.mark.integration
class TestRealDLLIntegration:
    def test_real_dll_live_connect_and_trade(self, simulator_env: dict[str, str]) -> None:
        require_dll_and_credentials(simulator_env)

        from profitdll_wrapper._bindings.functions import get_backend

        backend = get_backend()
        assert backend is not None

        key = simulator_env["ACTIVATION_KEY"]
        user = simulator_env["USER"]
        password = simulator_env["PASSWORD"]

        trades_received: list[Trade] = []

        try:
            with ProfitClient(
                activation_key=key,
                user=user,
                password=password,
                mode="market_data",
                backend=backend,
            ) as client:
                assert client.is_connected

                client.subscribe("DOLU26", exchange="F")

                @client.on(Event.TRADE)
                def on_trade(trade: Trade) -> None:
                    trades_received.append(trade)

                # Run the event loop in the background for 3 seconds.
                timer = threading.Timer(3.0, client.stop)
                timer.start()
                try:
                    client.run()
                finally:
                    timer.cancel()

            # Clean teardown completed without exception.
            assert not client.is_connected
        except BaseException as exc:
            # Same policy as the routing tests: live connection/auth failures
            # (external infra) become skips; everything else fails.
            skip_on_live_infra_error(exc, context="Live connection unavailable")
