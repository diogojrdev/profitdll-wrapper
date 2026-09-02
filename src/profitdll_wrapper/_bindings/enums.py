"""Connection state enums, order statuses, and exchange codes for ProfitDLL.

Values strictly map to the ProfitDLL native protocol integer codes.
"""

from __future__ import annotations

from enum import Enum, IntEnum


class ConnectionState(IntEnum):
    """Connection domains reported by TStateCallback (nConnStateType parameter)."""

    LOGIN = 0
    """Login and authentication server."""

    ROUTING = 1
    """Order routing server (active in 'routing' or 'full' mode).

    Member renamed from the vendor's Portuguese ``ROTEAMENTO``; ABI value
    is unchanged.
    """

    MARKET_DATA = 2
    """Market data server."""

    MARKET_LOGIN = 3
    """Market data service license/activation."""


class LoginResult(IntEnum):
    """nResult values when nConnStateType == ConnectionState.LOGIN."""

    CONNECTED = 0
    INVALID = 1
    """Invalid login credentials (key or user)."""

    INVALID_PASS = 2
    """Invalid password."""

    BLOCKED_PASS = 3
    """Blocked password."""

    EXPIRED_PASS = 4
    """Expired password."""

    UNKNOWN_ERR = 200
    """Internal login error."""


class RoutingResult(IntEnum):
    """nResult values when nConnStateType == ConnectionState.ROUTING."""

    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    """Connected to routing server."""

    BROKER_DISCONNECTED = 3
    BROKER_CONNECTING = 4
    BROKER_CONNECTED = 5
    """Connected to brokerage (fully connected routing state)."""


class MarketResult(IntEnum):
    """nResult values when nConnStateType == ConnectionState.MARKET_DATA."""

    DISCONNECTED = 0
    CONNECTING = 1
    WAITING = 2
    NOT_LOGGED = 3
    CONNECTED = 4
    """Connected to market data (OK state)."""

    PERFORMANCE_WARNING = 5
    """Performance warning reported by server."""

    PARTIAL_CONNECTED = 6
    """Local callback delivery stalled (risk of data loss)."""


class ActivationResult(IntEnum):
    """nResult values when nConnStateType == ConnectionState.MARKET_LOGIN."""

    VALID = 0
    """Valid activation (OK state)."""

    INVALID = 1
    """Invalid activation."""


class BookActionType(IntEnum):
    """Book action type in OfferBook / PriceBook callbacks."""

    ADD = 0
    EDIT = 1
    DELETE = 2
    DELETE_FROM = 3
    FULL_BOOK = 4


class BookSide(IntEnum):
    """Book side (0=Buy, 1=Sell, 254=Both)."""

    BUY = 0
    SELL = 1
    BOTH = 254
    NONE = 255


class BookUpdateType(IntEnum):
    """Price depth update type."""

    ADD = 0
    EDIT = 1
    DELETE = 2
    INSERT = 3
    FULL_BOOK = 4
    """Full snapshot available via get_price_group()."""

    PREPARE = 5
    FLUSH = 6
    THEORIC_PRICE = 7
    DELETE_FROM = 8


class OrderSide(IntEnum):
    """Order side for routing (1=Buy, 2=Sell)."""

    BUY = 1
    SELL = 2


class PositionType(IntEnum):
    """Position type for positions query."""

    DAY_TRADE = 1
    CONSOLIDATED = 2


class OrderStatus(IntEnum):
    """Execution status reported by ProfitDLL (TConnectorOrderStatus)."""

    NEW = 0
    PARTIALLY_FILLED = 1
    FILLED = 2
    DONE_FOR_DAY = 3
    CANCELED = 4
    CANCELLED = 4  # Convenience alias
    REPLACED = 5
    PENDING_CANCEL = 6
    STOPPED = 7
    REJECTED = 8
    SUSPENDED = 9
    PENDING_NEW = 10
    CALCULATED = 11
    EXPIRED = 12
    ACCEPTED_FOR_BIDDING = 13
    PENDING_REPLACE = 14
    PARTIALLY_FILLED_CANCELED = 15
    RECEIVED = 16
    PARTIALLY_FILLED_EXPIRED = 17
    PARTIALLY_FILLED_REJECTED = 18
    UNKNOWN = 200
    HADES_CREATED = 201
    BROKER_SENT = 202
    CLIENT_CREATED = 203
    ORDER_NOT_CREATED = 204
    CANCELED_BY_ADMIN = 205
    DELAY_FIX_GATEWAY = 206
    SCHEDULED_ORDER = 207


class OrderType(IntEnum):
    """Routing order type (TConnectorOrderType)."""

    MARKET = 1
    LIMIT = 2
    STOP = 4
    STOP_LIMIT = 4  # Official documented alias


class AccountType(IntEnum):
    """Trading account type (TConnectorAccountType)."""

    OWNER = 0
    ASSESSOR = 1
    MASTER = 2
    SUB_ACCOUNT = 3
    RISK_MASTER = 4
    PROP_OFFICE = 5
    PROP_MANAGER = 6


class TradeType(IntEnum):
    """Trade type flag in trade callback (TTradeType)."""

    CROSS_TRADE = 1
    AGGRESSOR_BUYER = 2
    AGGRESSOR_SELLER = 3
    AUCTION = 4
    SURVEILLANCE = 5
    EXPIT = 6
    OPTION_EXERCISE = 7
    OVER_THE_COUNTER = 8
    DERIVATIVE_TERM = 9
    INDEX = 10
    BTC = 11
    ON_BEHALF = 12
    RLP = 13
    BBT = 14
    RFQ = 15
    MPT = 16
    TAC = 17
    TAA = 18
    UNKNOWN = 32
    UPDATE = 33
    MID = 34
    OFF_EXCHANGE = 35


class TickerState(IntEnum):
    """Ticker state in TChangeStateTicker callback."""

    OPENED = 0
    FROZEN = 2
    INHIBITED = 3
    AUCTIONED = 4
    CLOSED = 6
    PRE_CLOSING = 10
    PRE_OPENING = 13
    UNKNOWN = 255


class TradingMessageResultCode(IntEnum):
    """Trading message result code (TConnectorTradingMessageResultCode).

    Delivered through ``Event.TRADING_MESSAGE`` as ``result_code``. A healthy
    order flows ``STARTING -> SENT_TO_HADES_PROXY -> SENT_TO_HADES ->
    SENT_TO_BROKER -> SENT_TO_MARKET -> ACCEPTED``; the ``REJECTED_*`` values
    abort that chain. An order that stalls after ``SENT_TO_HADES`` was dropped
    by the order server (e.g. invalid routing password) without a rejection
    event.
    """

    STARTING = 0
    NOT_CONNECTED = 1
    SENT_TO_HADES_PROXY = 2
    REJECTED_MERCURY = 3
    SENT_TO_HADES = 4
    REJECTED_HADES = 5
    SENT_TO_BROKER = 6
    REJECTED_BROKER = 7
    SENT_TO_MARKET = 8
    REJECTED_MARKET = 9
    ACCEPTED = 10
    MARGIN_TYPE_CHANGE_REJECTED = 11
    POSITION_MODE_CHANGE_REJECTED = 12
    NEED_UPDATE_FROM_SERVER = 13
    SENT_TO_WALLET = 17
    BLOCKED_BY_RISK = 24
    SUB_ACCOUNT = 50
    SUB_ACCOUNT_PLAN = 51
    SUB_ACCOUNT_RESET_LIMIT = 52
    SUB_ACCOUNT_BROKERAGE = 53
    SUB_ACCOUNT_BROKERAGE_PREFIX = 54
    SUB_ACCOUNT_GROUP = 55
    SUB_ACCOUNT_GROUP_INSERTION = 56
    RISK_GROUP = 60
    RISK_PREFIX = 61
    RISK_ACCOUNT = 62
    RESET_PASSWORD_RESULT = 63
    FIN_EDIT_TRADE_RESULT_SUCCESS = 70
    FIN_TRADE_RESULT_ERROR = 71
    SUB_ACCOUNT_PREFIX_SUCCESS = 74
    SUB_ACCOUNT_PREFIX_ERROR = 75
    FINANCIAL_LOSS_SUCCESS = 76
    INVALID_DATA = 77
    INVALID_WALLET_TRANSFER = 78
    SUB_ACCOUNT_ASSETS_UPDATE_SUCCESS = 79
    SUB_ACCOUNT_ASSETS_UPDATE_ERROR = 80
    UNKNOWN = 200


class ExchangeCode(str, Enum):
    """Exchange codes accepted by SubscribeTicker."""

    BCB = "A"
    """Central Bank of Brazil (economic indicators)."""

    BOVESPA = "B"
    """B3 Bovespa (equities and options)."""

    CAMBIO = "D"
    """Foreign Exchange (FX)."""

    ECONOMIC = "E"
    """Economic indicators."""

    BMF = "F"
    """B3 BMF (futures and commodities)."""

    METRICS = "K"
    CME = "M"
    NASDAQ = "N"
    OXR = "O"
    PIONEER = "P"
    DOW_JONES = "X"
    NYSE = "Y"


class SystemHealthState(IntEnum):
    """Aggregated health state of internal DLL threads (v4.0.0.41)."""

    RESPONSIVE = 0
    """Main and Calc threads are responsive (OK state)."""

    FROZEN = 1
    """Main or Calc thread is frozen."""


# OK result codes by connection state domain:
OK_RESULT_BY_STATE: dict[ConnectionState, int] = {
    ConnectionState.LOGIN: int(LoginResult.CONNECTED),
    ConnectionState.ROUTING: int(RoutingResult.BROKER_CONNECTED),
    ConnectionState.MARKET_DATA: int(MarketResult.CONNECTED),
    ConnectionState.MARKET_LOGIN: int(ActivationResult.VALID),
}

# Connection domains required for each operating mode:
MARKET_DATA_STATES = frozenset(
    {ConnectionState.LOGIN, ConnectionState.MARKET_DATA, ConnectionState.MARKET_LOGIN}
)
ROUTING_STATES = frozenset(
    {
        ConnectionState.LOGIN,
        ConnectionState.ROUTING,
        ConnectionState.MARKET_DATA,
        ConnectionState.MARKET_LOGIN,
    }
)
