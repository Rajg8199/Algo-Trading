"""Market time utilities. The platform thinks in IST; storage is UTC.

Holiday data lives in the `events` table (event_type=HOLIDAY) and is loaded
by callers; these helpers are pure functions over wall-clock time.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
PRE_OPEN_START = time(9, 0)


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("naive datetime rejected; all timestamps must be tz-aware")
    return ts.astimezone(IST)


def is_market_hours(ts: datetime, holidays: frozenset[date] = frozenset()) -> bool:
    """True if ts falls inside the NSE/BSE continuous session."""
    local = to_ist(ts)
    if local.weekday() >= 5 or local.date() in holidays:
        return False
    return MARKET_OPEN <= local.time() <= MARKET_CLOSE


def trade_date(ts: datetime) -> date:
    """The trading date a timestamp belongs to (IST calendar date)."""
    return to_ist(ts).date()


def next_session_open(ts: datetime, holidays: frozenset[date] = frozenset()) -> datetime:
    """Next market open strictly after ts."""
    local = to_ist(ts)
    candidate = local.date()
    if local.time() >= MARKET_OPEN:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in holidays:
        candidate += timedelta(days=1)
    return datetime.combine(candidate, MARKET_OPEN, tzinfo=IST)
