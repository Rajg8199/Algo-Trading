from datetime import UTC, date, datetime

import pytest

from tp_core.timeutils import IST, is_market_hours, next_session_open, to_ist, trade_date


def ist(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_market_hours_open() -> None:
    assert is_market_hours(ist(2026, 6, 11, 10, 0))  # Thursday mid-session


def test_market_hours_before_open_and_after_close() -> None:
    assert not is_market_hours(ist(2026, 6, 11, 9, 0))
    assert not is_market_hours(ist(2026, 6, 11, 15, 31))


def test_market_hours_weekend_and_holiday() -> None:
    assert not is_market_hours(ist(2026, 6, 13, 10, 0))  # Saturday
    holiday = frozenset({date(2026, 6, 11)})
    assert not is_market_hours(ist(2026, 6, 11, 10, 0), holiday)


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        to_ist(datetime(2026, 6, 11, 10, 0))


def test_trade_date_crosses_utc_midnight() -> None:
    # 20:00 UTC = 01:30 IST next day
    ts = datetime(2026, 6, 11, 20, 0, tzinfo=UTC)
    assert trade_date(ts) == date(2026, 6, 12)


def test_next_session_open_skips_weekend() -> None:
    friday_close = ist(2026, 6, 12, 15, 30)
    nxt = next_session_open(friday_close)
    assert nxt == ist(2026, 6, 15, 9, 15)  # Monday
