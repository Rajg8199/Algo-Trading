from datetime import UTC, datetime
from decimal import Decimal

from tp_core.models import ChainRow, Tick
from tp_recorder.validators import TickValidator, validate_chain_row

NOW = datetime(2026, 6, 11, 10, 0, tzinfo=UTC)


def tick(ltp: str, bid: str | None = None, ask: str | None = None, iid: int = 1) -> Tick:
    return Tick(
        ts=NOW,
        instrument_id=iid,
        ltp=Decimal(ltp),
        bid=Decimal(bid) if bid else None,
        ask=Decimal(ask) if ask else None,
    )


def test_accepts_normal_tick() -> None:
    assert TickValidator().validate(tick("24500.50", "24500.00", "24501.00"))


def test_rejects_nonpositive_ltp() -> None:
    assert not TickValidator().validate(tick("0"))


def test_rejects_crossed_quote() -> None:
    assert not TickValidator().validate(tick("100", bid="101", ask="100"))


def test_rejects_index_price_jump() -> None:
    v = TickValidator()
    assert v.validate(tick("24500"))
    assert not v.validate(tick("30000"))  # +22% in one update on an index level


def test_allows_option_premium_jump() -> None:
    v = TickValidator()
    assert v.validate(tick("100", iid=2))
    assert v.validate(tick("140", iid=2))  # +40% on a cheap option is normal


def test_chain_row_validation() -> None:
    good = ChainRow(ts=NOW, instrument_id=1, bid=Decimal(10), ask=Decimal(11), oi=100, iv=14.5)
    assert validate_chain_row(good)
    crossed = ChainRow(ts=NOW, instrument_id=1, bid=Decimal(12), ask=Decimal(11))
    assert not validate_chain_row(crossed)
    bad_iv = ChainRow(ts=NOW, instrument_id=1, iv=900.0)
    assert not validate_chain_row(bad_iv)
