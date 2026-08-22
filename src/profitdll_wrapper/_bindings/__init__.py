"""ctypes bindings layer.

This module directly interfaces with ``ctypes`` to declare DLL function signatures.

Responsibilities:
* Load ``ProfitDLL.dll`` (``WinDLL`` = ``stdcall``), resolving bitness (32/64-bit)
  and binary location (``PROFITDLL_PATH`` env var or default path).
* Explicitly declare ``argtypes`` and ``restype`` for all exported functions.
* Translate ``NL_*`` error codes into ``IntEnum`` and typed exception hierarchy.

The public API should never import directly from this internal module.
"""
