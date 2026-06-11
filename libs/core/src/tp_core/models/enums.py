from enum import StrEnum


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


class Segment(StrEnum):
    INDEX = "INDEX"
    FUT = "FUT"
    OPT = "OPT"


class OptionType(StrEnum):
    CE = "CE"
    PE = "PE"


class TradingMode(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    PENDING_RISK = "PENDING_RISK"
    REJECTED_RISK = "REJECTED_RISK"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class Severity(StrEnum):
    """Alert severities. P1 pages immediately, P2 batches, INFO goes to the digest."""

    P1 = "P1"
    P2 = "P2"
    INFO = "INFO"
