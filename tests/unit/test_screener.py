"""Breakout scanner + backtest tests. Synthetic series are constructed so each
rule (breakout / trend / volume / stop) can be asserted in isolation — the
point of the package is honesty, so the tests pin the math, not vibes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from tp_research.screener import (
    BreakoutParams,
    DailyBar,
    backtest_symbol,
    evaluate_breakout,
    scan,
    summarize,
)
from tp_research.screener.indicators import atr, highest, lowest, sma

START = date(2024, 1, 1)


def make_bars(
    closes: Sequence[float], volumes: Sequence[float], symbol: str = "TEST", pad: float = 0.2
) -> list[DailyBar]:
    # pad is the intraday wick; keep it smaller than the day-to-day step so a
    # rising close genuinely clears prior intraday highs (a real breakout).
    bars: list[DailyBar] = []
    prev = closes[0]
    for i, (c, v) in enumerate(zip(closes, volumes, strict=True)):
        o = prev
        hi = max(o, c) + pad
        lo = min(o, c) - pad
        bars.append(DailyBar(symbol, START + timedelta(days=i), o, hi, lo, c, v))
        prev = c
    return bars


# ---- indicators ----------------------------------------------------------


def test_sma_and_extremes() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert sma(vals, 5) == 3.0
    assert sma(vals, 2) == 4.5
    assert sma(vals, 6) is None
    assert highest(vals, 3) == 5.0
    assert lowest(vals, 3) == 3.0


def test_atr_positive_and_guarded() -> None:
    highs = [10.0, 11.0, 12.0, 13.0]
    lows = [9.0, 9.5, 10.0, 11.0]
    closes = [9.5, 10.5, 11.5, 12.5]
    assert atr(highs, lows, closes, 3) is not None
    assert atr(highs, lows, closes, 10) is None  # not enough bars


# ---- signal rules --------------------------------------------------------


def _rising(n: int = 220) -> list[float]:
    return [100.0 + i * 1.0 for i in range(n)]


def test_breakout_fires_on_trend_volume_and_new_high() -> None:
    closes = _rising()
    volumes = [1000.0] * (len(closes) - 1) + [3000.0]  # spike on the signal day
    sig = evaluate_breakout(make_bars(closes, volumes), BreakoutParams())
    assert sig is not None
    assert sig.stop < sig.entry  # real risk geometry
    assert sig.risk_per_share > 0
    assert sig.volume_ratio > 1.5
    assert sig.position_size(capital=1_000_000, risk_pct=0.01) > 0


def test_no_signal_without_volume_confirmation() -> None:
    closes = _rising()
    volumes = [1000.0] * len(closes)  # no spike → ratio ~1.0
    assert evaluate_breakout(make_bars(closes, volumes), BreakoutParams()) is None


def test_no_signal_without_new_high() -> None:
    # rise, then a flat plateau at the top so today's close cannot exceed the
    # prior days' intraday highs
    base = _rising(200)
    closes = base + [base[-1]] * 25
    volumes = [1000.0] * (len(closes) - 1) + [5000.0]
    assert evaluate_breakout(make_bars(closes, volumes), BreakoutParams()) is None


def test_trend_filter_blocks_downtrend_pop() -> None:
    # long decline, then a flat base, then a pop that clears the BASE's 20-day
    # high while price is still far below its 200-SMA → breakout true, trend
    # false → no signal (with the filter on).
    decline = [300.0 - i * 0.85 for i in range(200)]
    base_val = decline[-1]
    closes = decline + [base_val] * 20 + [base_val + 5.0]  # 221 bars; last = pop
    volumes = [1000.0] * (len(closes) - 1) + [5000.0]
    assert evaluate_breakout(make_bars(closes, volumes), BreakoutParams()) is None
    # with the trend filter off, the breakout+volume alone fires
    sig = evaluate_breakout(make_bars(closes, volumes), BreakoutParams(require_trend=False))
    assert sig is not None


def test_scan_sorts_by_conviction() -> None:
    weak = make_bars(_rising(), [1000.0] * 219 + [1600.0], symbol="WEAK")
    strong = make_bars(_rising(), [1000.0] * 219 + [4000.0], symbol="STRONG")
    out = scan({"WEAK": weak, "STRONG": strong}, BreakoutParams())
    assert [s.symbol for s in out] == ["STRONG", "WEAK"]


# ---- backtest ------------------------------------------------------------


def test_backtest_winner_is_profitable() -> None:
    closes = _rising(260)
    volumes = [1000.0] * len(closes)
    volumes[205] = 4000.0  # one clean breakout trigger mid-series
    trades = backtest_symbol(make_bars(closes, volumes), BreakoutParams())
    assert len(trades) >= 1
    res = summarize(trades, BreakoutParams())
    assert res.expectancy_r is not None and res.expectancy_r > 0
    assert res.total_return_pct > 0


def test_backtest_stops_out_on_reversal() -> None:
    # clean breakout, then a hard reversal that must trip the stop
    closes = _rising(230)
    closes = closes + [closes[-1] - 8.0 * (i + 1) for i in range(15)]
    volumes = [1000.0] * len(closes)
    volumes[205] = 4000.0
    trades = backtest_symbol(make_bars(closes, volumes), BreakoutParams())
    assert any(t.reason in {"stop", "gap_stop"} for t in trades)


def test_empty_backtest_is_safe() -> None:
    res = summarize([], BreakoutParams())
    assert res.n_trades == 0
    assert res.profit_factor is None
    assert not res.acceptable  # zero trades can never be acceptable
