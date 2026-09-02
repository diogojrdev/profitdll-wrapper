"""Shared utility functions for profitdll-wrapper examples and scripts.

Credential and DLL-path resolution delegate to :mod:`profitdll_wrapper._config`
so examples and the library can never drift apart.
"""

from __future__ import annotations

from pathlib import Path

from profitdll_wrapper._config import (
    load_credentials as _load_credentials_map,
    load_env_file,
    setup_dll_path,
)

__all__ = ["load_credentials", "load_env", "setup_dll_path"]


def load_credentials() -> tuple[str, str, str, str, str]:
    """Loads ``(activation_key, user, password, account, routing_key)``.

    ``routing_key`` comes from ``PROFITDLL_ROUTING_KEY``/``ROUTING_KEY`` and is
    required by every order-routing call (mode="routing"). It is returned
    as-is: an empty string when not configured. There is deliberately NO
    fallback to the login ``password`` — they are distinct credentials, and
    sending the login password makes the order server drop orders silently
    and can lock the account. Routing examples must abort when it is empty.
    """
    creds = _load_credentials_map()
    return (
        creds["activation_key"],
        creds["user"],
        creds["password"],
        creds["account"],
        creds["routing_key"],
    )


def load_env(env_path: Path | str | None = None) -> dict[str, str]:
    """Parses a ``.env`` file into a dict (default: repo-root ``.env``)."""
    return load_env_file(env_path)
