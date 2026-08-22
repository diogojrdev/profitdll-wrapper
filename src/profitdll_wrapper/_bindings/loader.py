"""Native ProfitDLL loading module.

Resolves binary path dynamically at runtime via:
1. Environment variable PROFITDLL_PATH (absolute path to DLL).
2. ProfitDLL.dll / ProfitDLL64.dll in the project's dll/ directory.

Supported platform: Windows OS only (ProfitDLL is Windows-native).
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import sys
from contextlib import suppress
from pathlib import Path

from profitdll_wrapper._bindings.errors import PlatformNotSupportedError

PROFITDLL_PATH_ENV = "PROFITDLL_PATH"

_logger = logging.getLogger("profitdll_wrapper.bindings")


def _bits() -> int:
    """Returns 64 or 32 depending on current Python interpreter architecture."""
    return 64 if sys.maxsize > 2**32 else 32


def _candidate_filenames(bits: int) -> list[str]:
    """Candidate filenames to try for specified architecture bitness."""
    if bits == 64:
        return ["ProfitDLL64.dll", "ProfitDLL.dll"]
    return ["ProfitDLL.dll"]


def _resolve_dll_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolves DLL path to load.

    Precedence order:
      1. explicit path argument
      2. PROFITDLL_PATH environment variable
      3. dll/<filename> in working directory

    The bare working directory is intentionally NOT searched: loading a DLL
    from an untrusted current directory would let a planted binary run with
    the process's privileges (DLL planting).

    Raises:
        FileNotFoundError: If no candidate path exists.
    """
    bits = _bits()
    filenames = _candidate_filenames(bits)

    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    env_value = os.environ.get(PROFITDLL_PATH_ENV)
    if env_value:
        candidates.append(Path(env_value))
    candidates.extend(Path("dll") / fn for fn in filenames)

    for cand in candidates:
        if cand.is_file():
            resolved = cand.resolve()
            if explicit is None and not env_value:
                _logger.warning(
                    "Loading ProfitDLL from working-directory fallback %s. "
                    "Prefer passing an explicit path or setting %s.",
                    resolved,
                    PROFITDLL_PATH_ENV,
                )
            return resolved

    searched = "\n  - ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"ProfitDLL not found ({bits}-bit architecture). Set environment variable "
        f"{PROFITDLL_PATH_ENV}=<path to ProfitDLL.dll> or place DLL in ./dll/. "
        f"Searched paths:\n  - {searched}"
    )


def _load_dll(
    explicit: str | os.PathLike[str] | None = None,
) -> ctypes.WinDLL:
    """Loads ProfitDLL and returns WinDLL (stdcall) handle.

    Args:
        explicit: Optional explicit file path to DLL.

    Raises:
        PlatformNotSupportedError: If running on non-Windows OS.
        FileNotFoundError: If DLL file cannot be located.
        OSError: If WinDLL fails to load binary.
    """
    if platform.system() != "Windows":
        raise PlatformNotSupportedError(
            f"ProfitDLL is Windows-only; cannot load on {platform.system()}."
        )

    dll_path = _resolve_dll_path(explicit)
    dll_dir = str(dll_path.parent.resolve())
    if hasattr(os, "add_dll_directory"):
        with suppress(Exception):
            os.add_dll_directory(dll_dir)
    return ctypes.WinDLL(str(dll_path))


__all__ = [
    "PROFITDLL_PATH_ENV",
    "_bits",
    "_candidate_filenames",
    "_load_dll",
    "_resolve_dll_path",
]
