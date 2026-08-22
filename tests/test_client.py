"""Testes agregadores do ProfitClient (re-exporta suítes decompostas para compatibilidade de discovery)."""

from __future__ import annotations

from tests.test_client_accounts import TestAccounts, TestAgentName
from tests.test_client_lifecycle import (
    TestConnect,
    TestContextManager,
    TestPublicAPI,
)
from tests.test_client_market_data import (
    TestChangeStateTicker,
    TestDailyCallback,
    TestMarketWarnings,
    TestPriceDepthCallback,
    TestPriceDepthSubscribe,
    TestReadTheoreticalPrice,
    TestRequestTickerInfo,
    TestSubscribe,
    TestTradeFlow,
)

__all__ = [
    "TestAccounts",
    "TestAgentName",
    "TestChangeStateTicker",
    "TestConnect",
    "TestContextManager",
    "TestDailyCallback",
    "TestMarketWarnings",
    "TestPriceDepthCallback",
    "TestPriceDepthSubscribe",
    "TestPublicAPI",
    "TestReadTheoreticalPrice",
    "TestRequestTickerInfo",
    "TestSubscribe",
    "TestTradeFlow",
]
