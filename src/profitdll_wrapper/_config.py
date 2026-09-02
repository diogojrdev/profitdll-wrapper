"""Environment and credential loading for the library and CLI.

Promotes the ad-hoc ``.env`` parsing previously living in
``examples/_common.py`` into the library so the CLI (and any tooling) can
source credentials without depending on example code. Uses only the standard
library — no ``python-dotenv`` dependency.

Resolution order for every credential key: process environment first, then
the root ``.env`` file. Several historical alias names are accepted for each
logical credential.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Environment variable that points at the native DLL binary.
PROFITDLL_PATH_ENV = "PROFITDLL_PATH"


def repo_root() -> Path:
    """Returns the project repository root (best-effort, based on this file's location)."""
    return _REPO_ROOT


def load_env_file(env_path: Path | str | None = None) -> dict[str, str]:
    """Parses a ``.env`` file into a dict (default: repo-root ``.env``).

    Skips blank lines and comments (``#``). Strips surrounding quotes from
    values. Returns an empty dict if the file is absent.
    """
    target = Path(env_path) if env_path is not None else _REPO_ROOT / ".env"
    out: dict[str, str] = {}
    if not target.is_file():
        return out
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip()
        # Inline comments ("KEY=value  # comment") are not part of the value.
        # Only strip when '#' is preceded by whitespace so values containing
        # '#' without a leading space survive intact.
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        out[key.strip()] = val.strip("'\"")
    return out


def _first(env_names: list[str], file_names: list[str], env: dict[str, str]) -> str:
    """First non-empty value: PROFITDLL_* process env vars, then ``.env`` entries.

    Only ``PROFITDLL_*``-prefixed names are read from the process environment:
    generic names such as ``USER``/``PASSWORD`` exist in nearly every POSIX
    shell and would silently send OS credentials as the ProfitDLL login. The
    unprefixed names remain valid inside the ``.env`` file, where they are
    project-scoped.
    """
    for name in env_names:
        val = os.environ.get(name)
        if val:
            return val
    for name in file_names:
        val = env.get(name)
        if val:
            return val
    return ""


def load_credentials(env_path: Path | str | None = None) -> dict[str, str]:
    """Loads ProfitDLL credentials from environment and/or ``.env``.

    Returns a dict with keys ``activation_key``, ``user``, ``password``,
    ``account``, ``broker`` and ``routing_key``. Missing credentials are
    returned as empty strings.

    ``routing_key`` is the routing password required by every order-routing
    call (``SendOrder``/``SendCancel*``/``SendChangeOrderV2``/
    ``SendZeroPositionV2``). It is a credential distinct from the login
    ``password``: the order server (Hades) validates it before forwarding
    orders to the broker, and sending the login password instead causes
    silent rejections that can lock the account. No fallback to ``password``
    is applied here — an empty string means the caller must decide.
    """
    env = load_env_file(env_path)
    return {
        "activation_key": _first(
            ["PROFITDLL_ACTIVATION_KEY", "PROFITDLL_WRAPPER_ACTIVATION_KEY"],
            ["PROFITDLL_ACTIVATION_KEY", "PROFITDLL_WRAPPER_ACTIVATION_KEY", "ACTIVATION_KEY"],
            env,
        ),
        "user": _first(
            ["PROFITDLL_USER", "PROFITDLL_WRAPPER_USER"],
            ["PROFITDLL_USER", "PROFITDLL_WRAPPER_USER", "USER"],
            env,
        ),
        "password": _first(
            ["PROFITDLL_PASSWORD", "PROFITDLL_WRAPPER_PASSWORD"],
            ["PROFITDLL_PASSWORD", "PROFITDLL_WRAPPER_PASSWORD", "PASSWORD"],
            env,
        ),
        "routing_key": _first(
            ["PROFITDLL_ROUTING_KEY", "PROFITDLL_WRAPPER_ROUTING_KEY"],
            ["PROFITDLL_ROUTING_KEY", "PROFITDLL_WRAPPER_ROUTING_KEY", "ROUTING_KEY"],
            env,
        ),
        "account": _first(
            ["PROFITDLL_ACCOUNT", "PROFITDLL_WRAPPER_ACCOUNT"],
            ["PROFITDLL_ACCOUNT", "PROFITDLL_WRAPPER_ACCOUNT", "ACCOUNT_ID"],
            env,
        ),
        "broker": _first(
            ["PROFITDLL_BROKER", "PROFITDLL_WRAPPER_BROKER"],
            ["PROFITDLL_BROKER", "PROFITDLL_WRAPPER_BROKER", "BROKER"],
            env,
        ),
    }


def setup_dll_path(env_path: Path | str | None = None) -> Path | None:
    """Sets ``PROFITDLL_PATH`` from the repo ``dll/`` dir if it is not already set.

    Returns the resolved DLL path, or ``None`` if no local DLL was found.
    """
    if os.environ.get(PROFITDLL_PATH_ENV):
        return Path(os.environ[PROFITDLL_PATH_ENV])
    for candidate in ("ProfitDLL64.dll", "ProfitDLL.dll"):
        path = _REPO_ROOT / "dll" / candidate
        if path.is_file():
            os.environ[PROFITDLL_PATH_ENV] = str(path)
            return path
    _ = env_path  # accepted for API symmetry with load_credentials
    return None


__all__ = [
    "PROFITDLL_PATH_ENV",
    "load_credentials",
    "load_env_file",
    "repo_root",
    "setup_dll_path",
]
