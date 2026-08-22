"""Shared helpers for integration tests against the real profitdll_wrapper binary.

Centralizes the environment/credential gate (``require_dll_and_credentials``)
that every integration test runs before touching the native DLL, plus the
policy that converts live connection failures into skips while letting real
wrapper bugs surface as failures.
"""

from __future__ import annotations

import platform

import pytest

from profitdll_wrapper._bindings.errors import AuthError, ProfitConnectionError
from profitdll_wrapper._bindings.loader import _resolve_dll_path

# Exceptions that indicate the live simulator/server is unreachable or rejected
# authentication: these depend on external infrastructure, so they become skips.
# Any other exception (TypeError, AssertionError, etc.) is a real wrapper bug
# and must surface as a test failure.
_LIVE_INFRA_ERRORS: tuple[type[BaseException], ...] = (ProfitConnectionError, AuthError)


def has_dll_and_credentials(env: dict[str, str]) -> tuple[bool, str]:
    """Returns (can_run, reason). True only on Windows with the native DLL
    resolvable and ACTIVATION_KEY/USER/PASSWORD present in ``env``."""
    if platform.system() != "Windows":
        return False, "DLL só pode rodar em Windows"
    try:
        _resolve_dll_path()
    except FileNotFoundError as exc:
        return False, f"DLL não encontrada: {exc}"
    for k in ("ACTIVATION_KEY", "USER", "PASSWORD"):
        if not env.get(k):
            return False, f"Credencial {k} ausente no .env"
    return True, "OK"


def require_dll_and_credentials(env: dict[str, str]) -> None:
    """Skips the calling test unless the DLL and credentials are available."""
    can_run, reason = has_dll_and_credentials(env)
    if not can_run:
        pytest.skip(reason)


def skip_on_live_infra_error(exc: BaseException, *, context: str) -> None:
    """Converts live connection/auth failures into skips; re-raises everything else.

    Use this around code that talks to the live simulator so flakiness in the
    external server does not fail CI, while genuine wrapper bugs still fail.
    """
    if isinstance(exc, _LIVE_INFRA_ERRORS):
        pytest.skip(f"{context}: {exc}")
    raise exc
