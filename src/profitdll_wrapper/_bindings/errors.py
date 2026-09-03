"""ProfitDLL NL_* error codes and exception hierarchy.

Hierarchical exception tree:

    ProfitError                       — Root exception for profitdll-wrapper
    ├── ProfitAPIError(code)          — Exceptions with an NL_* error code
    │   ├── AuthError                 — Authentication/license/login failures
    │   ├── InvalidArgumentError      — Invalid tickers, parameters, or dates
    │   │   └── HistoryPeriodLimitError — History start older than 30 days
    │   └── ServerStateError          — Server state issues
    ├── ProfitConnectionError               — Connection timeouts / network failures
    └── PlatformNotSupportedError     — OS or architecture incompatibility
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final


class NLCode(IntEnum):
    """ProfitDLL return codes (matching vendor specification)."""

    OK = 0x00000000
    INTERNAL_ERROR = 0x80000001
    NOT_INITIALIZED = 0x80000002
    INVALID_ARGS = 0x80000003
    WAITING_SERVER = 0x80000004
    NO_LOGIN = 0x80000005
    NO_LICENSE = 0x80000006
    PASSWORD_HASH_SHA1 = 0x80000007
    PASSWORD_HASH_MD5 = 0x80000008
    OUT_OF_RANGE = 0x80000009
    MARKET_ONLY = 0x8000000A
    NO_POSITION = 0x8000000B
    NOT_FOUND = 0x8000000C
    VERSION_NOT_SUPPORTED = 0x8000000D
    OCO_NO_RULES = 0x8000000E
    EXCHANGE_UNKNOWN = 0x8000000F
    NO_OCO_DEFINED = 0x80000010
    INVALID_SERIE = 0x80000011
    LICENSE_NOT_ALLOWED = 0x80000012
    NOT_HARD_LOGOUT = 0x80000013
    SERIE_NO_HISTORY = 0x80000014
    ASSET_NO_DATA = 0x80000015
    SERIE_NO_DATA = 0x80000016
    HAS_STRATEGY_RUNNING = 0x80000017
    SERIE_NO_MORE_HISTORY = 0x80000018
    SERIE_MAX_COUNT = 0x80000019
    DUPLICATE_RESOURCE = 0x8000001A
    UNSIGNED_CONTRACT = 0x8000001B
    NO_PASSWORD = 0x8000001C
    NO_USER = 0x8000001D
    FILE_ALREADY_EXISTS = 0x8000001E
    INVALID_TICKER = 0x8000001F
    NOT_MASTER_ACCOUNT = 0x80000020
    HISTORY_PERIOD_LIMIT = 0x8000002E


# Return codes representing success.
_OK_CODES: Final[frozenset[int]] = frozenset({NLCode.OK})


class ProfitError(Exception):
    """Base exception class for all errors raised by profitdll_wrapper."""


class PlatformNotSupportedError(ProfitError):
    """Raised when OS or platform architecture is unsupported."""


class ProfitConnectionError(ProfitError):
    """Raised when connection to server times out or fails."""


class ProfitAPIError(ProfitError):
    """Raised when ProfitDLL returns a non-zero NL_* status code."""

    def __init__(self, code: NLCode) -> None:
        self.code: NLCode = code
        super().__init__(f"ProfitDLL error {code.name} ({int(code):#010x})")


class AuthError(ProfitAPIError):
    """Raised on authentication or license validation failure."""


class InvalidArgumentError(ProfitAPIError):
    """Raised when invalid parameters (ticker, dates) are supplied."""


class HistoryPeriodLimitError(InvalidArgumentError):
    """Raised when a historical request exceeds the 30-day server limit.

    Maps ``NL_HISTORY_PERIOD_LIMIT``: the server rejects requests whose start
    date is older than 30 days relative to the current server date. Split the
    range into <=30-day windows to backfill further back.
    """


class ServerStateError(ProfitAPIError):
    """Raised when server is not in expected state to handle request."""


# Map NL_* codes to specialized exception classes:
_CODE_TO_EXC: Final[dict[int, type[ProfitAPIError]]] = {
    int(NLCode.NO_LOGIN): AuthError,
    int(NLCode.NO_LICENSE): AuthError,
    int(NLCode.NO_PASSWORD): AuthError,
    int(NLCode.NO_USER): AuthError,
    int(NLCode.LICENSE_NOT_ALLOWED): AuthError,
    int(NLCode.INVALID_ARGS): InvalidArgumentError,
    int(NLCode.INVALID_TICKER): InvalidArgumentError,
    int(NLCode.HISTORY_PERIOD_LIMIT): HistoryPeriodLimitError,
    int(NLCode.OUT_OF_RANGE): InvalidArgumentError,
    int(NLCode.WAITING_SERVER): ServerStateError,
}


def _exception_for(code: int) -> ProfitAPIError:
    """Returns specialized exception instance for given NL_* return code."""
    code_uint = code & 0xFFFFFFFF if code < 0 else code
    try:
        nl = NLCode(code_uint)
    except ValueError:
        nl = NLCode.INTERNAL_ERROR
    exc_cls = _CODE_TO_EXC.get(int(nl), ProfitAPIError)
    return exc_cls(nl)


def _check(code: int) -> None:
    """Raises appropriate exception if `code` indicates failure."""
    if code in _OK_CODES or code == 0:
        return
    raise _exception_for(code)
