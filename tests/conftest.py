"""Shared pytest fixtures and configuration for profitdll-wrapper."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from profitdll_wrapper._bindings.enums import MARKET_DATA_STATES
from tests.fakes.backend import FakeProfitBackend


def load_env_file(path: Path | str = ".env") -> dict[str, str]:
    """Pure stdlib .env file parser."""
    env_vars: dict[str, str] = {}
    env_path = Path(path)
    if not env_path.is_file():
        return env_vars
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        env_vars[key] = value
    return env_vars


@pytest.fixture(autouse=True)
def _hermetic_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keeps unit tests independent of the developer's real .env.

    ProfitClient falls back to reading BROKER from the repo .env; patch that
    lookup (and any leaked env vars) so tests only use explicitly passed
    broker_id values.
    """
    import profitdll_wrapper.client._client as client_module

    monkeypatch.setattr(client_module, "_broker_from_env", lambda: None)
    monkeypatch.delenv("PROFITDLL_BROKER", raising=False)
    monkeypatch.delenv("BROKER", raising=False)


@pytest.fixture(autouse=True)
def _fresh_dll_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resets the process-wide "DLL already finalized" guard between tests.

    The guard is module state by design (the native DLL lifecycle is per
    process), but a test that finalizes a (mocked) backend must not poison
    the next test's get_backend() call.
    """
    import profitdll_wrapper._bindings.functions as functions_module

    monkeypatch.setattr(functions_module, "_dll_finalized", False)


@pytest.fixture
def fake_backend() -> FakeProfitBackend:
    """Pre-configured fake backend fixture configured to connect successfully in market_data mode."""
    backend = FakeProfitBackend()
    backend.connect_states = MARKET_DATA_STATES
    return backend


@pytest.fixture(scope="session")
def simulator_env() -> dict[str, str]:
    """Loads simulator credentials from root .env file if available."""
    env = load_env_file(".env")
    for k in ("ACTIVATION_KEY", "USER", "PASSWORD", "PROFITDLL_PATH"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers",
        "integration: marks tests requiring the native ProfitDLL binary and .env credentials",
    )
