"""Mean-reversion + RSI + walk-forward period-breakdown tests."""

from __future__ import annotations

from datetime import date, timedelta

from tp_research.screener.backtest import period_breakdown
from tp_research.screener.indicators import rsi
from tp_research.screener.meanrev import MeanRevParams, _entry_signal, backtest_meanrev_symbol
from tp_research.screener.models import BreakoutParams, DailyBar

START = date(2024, 1, 1)


def _bars(closes: list[float], pad: float = 0.2) -> list[DailyBar]:
    out: list[DailyBar] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        hi, lo = max(prev, c) + pad, min(prev, c) - pad
        out.append(DailyBar("X", START + timedelta(days=i), prev, hi, lo, c, 1000))
        prev = c
    return out


def test_rsi_extremes() -> None:
    assert rsi([1, 2, 3, 4, 5], 2) == 100.0  # only gains
    assert rsi([5, 4, 3, 2, 1], 2) == 0.0  # only losses
    mid = rsi([10, 11, 10, 11, 10], 2)
    assert mid is not None and 0 < mid < 100


def test_entry_fires_on_oversold_dip_in_uptrend() -> None:
    closes = [100.0 + i for i in range(220)]  # strong uptrend
    closes[-1] = closes[-2] - 12  # sharp 2-day-ish drop -> low RSI(2)
    closes[-2] = closes[-3] - 6
    stop = _entry_signal(_bars(closes), MeanRevParams())
    assert stop is not None
    assert stop < closes[-1]  # disaster stop sits below


def test_no_entry_in_downtrend() -> None:
    closes = [300.0 - i for i in range(220)]  # downtrend: below 200-SMA
    assert _entry_signal(_bars(closes), MeanRevParams()) is None


def _uptrend_with_dips(n: int = 320) -> list[float]:
    # +2/day uptrend, with a sharp TWO-day pullback every 25 days so RSI(2)
    # collapses below 10 and an entry fires
    closes: list[float] = []
    price = 100.0
    for i in range(n):
        if i > 0 and i % 25 in (0, 1):
            price -= 14.0  # two consecutive down days
        else:
            price += 2.0
        closes.append(price)
    return closes


def test_backtest_produces_trades_and_exits() -> None:
    trades = backtest_meanrev_symbol(_bars(_uptrend_with_dips()), MeanRevParams())
    assert len(trades) >= 1
    assert all(t.exit_day >= t.entry_day for t in trades)


def test_period_breakdown_splits_by_date() -> None:
    trades = backtest_meanrev_symbol(_bars(_uptrend_with_dips()), MeanRevParams())
    parts = period_breakdown(trades, BreakoutParams(), n_periods=3)
    assert len(parts) == 3
    assert sum(p[1].n_trades for p in parts) == len(trades)
