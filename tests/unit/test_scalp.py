"""EMA + intraday scalp signal tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from tp_research.scalp import ScalpBar, ScalpParams, scalp_signal
from tp_research.screener.indicators import ema

T0 = datetime(2026, 6, 15, 9, 30)


def _bar(i: int, o: float, h: float, low: float, c: float) -> ScalpBar:
    return ScalpBar(T0 + timedelta(minutes=3 * i), o, h, low, c)


def test_ema_tracks_and_guards() -> None:
    assert ema([5.0] * 10, 5) == 5.0  # flat -> flat
    assert ema([1.0, 2.0], 5) is None  # not enough points
    rising = ema([float(i) for i in range(30)], 9)
    assert rising is not None and rising < 29  # lags a rising series


def test_long_signal_on_pullback_in_uptrend() -> None:
    # build an uptrend so EMA9>EMA21, then a final bar that dips to the fast EMA
    # and closes back up (the pullback reclaim)
    bars = [_bar(i, 100 + i, 100 + i + 0.5, 100 + i - 0.5, 100 + i) for i in range(40)]
    last = bars[-1]
    # final bar: wick down then close above (reclaim)
    bars[-1] = ScalpBar(last.ts, last.open, last.close + 0.5, last.close - 8.0, last.close + 0.2)
    sig = scalp_signal(bars, ScalpParams())
    assert sig is not None
    assert sig.side == "LONG"
    assert sig.stop < sig.price < sig.target


def test_no_signal_when_flat() -> None:
    bars = [_bar(i, 100, 100.3, 99.7, 100) for i in range(40)]
    assert scalp_signal(bars, ScalpParams()) is None


def test_needs_enough_bars() -> None:
    bars = [_bar(i, 100, 101, 99, 100) for i in range(5)]
    assert scalp_signal(bars, ScalpParams()) is None
