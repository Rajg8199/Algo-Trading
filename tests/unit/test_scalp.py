"""EMA + tuned intraday scalp signal tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from tp_research.scalp import ScalpBar, ScalpParams, scalp_signal
from tp_research.screener.indicators import ema

T0 = datetime(2026, 6, 15, 9, 30)


def _mk(closes: list[float], pad: float = 0.3) -> list[ScalpBar]:
    out: list[ScalpBar] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        ts = T0 + timedelta(minutes=3 * i)
        out.append(ScalpBar(ts, prev, max(prev, c) + pad, min(prev, c) - pad, c))
        prev = c
    return out


def _noisy_uptrend(n: int = 40) -> list[float]:
    # net up-drift with bar-to-bar noise so RSI sits in the mid band (not extended)
    closes: list[float] = []
    p = 100.0
    for i in range(n):
        p += 0.6 + (0.8 if i % 2 == 0 else -0.9)
        closes.append(p)
    return closes


def test_ema_tracks_and_guards() -> None:
    assert ema([5.0] * 10, 5) == 5.0
    assert ema([1.0, 2.0], 5) is None
    rising = ema([float(i) for i in range(30)], 9)
    assert rising is not None and rising < 29


def test_long_signal_on_fresh_pullback_reclaim() -> None:
    closes = _noisy_uptrend(40)
    ef = ema(closes, 9)
    assert ef is not None
    bars = _mk(closes)
    # final bar wicks down to the fast EMA then closes back above it (upper range)
    final_close = ef + 1.0
    final_ts = bars[-1].ts + timedelta(minutes=3)
    bars.append(ScalpBar(final_ts, closes[-1], final_close + 0.3, ef - 2.0, final_close))
    sig = scalp_signal(bars, ScalpParams())
    assert sig is not None
    assert sig.side == "LONG"
    assert sig.stop < sig.price < sig.target


def test_rejects_extended_rsi() -> None:
    # monotonic strong uptrend -> RSI pinned high -> "don't chase" filter blocks it
    bars = _mk([100.0 + i for i in range(40)])
    assert scalp_signal(bars, ScalpParams()) is None


def test_rejects_dead_tape() -> None:
    # near-zero range (pad=0): ATR/price below the floor -> no scalp
    bars = _mk([100.0 + (0.01 if i % 2 else 0.0) for i in range(40)], pad=0.0)
    assert scalp_signal(bars, ScalpParams()) is None


def test_needs_enough_bars() -> None:
    assert scalp_signal(_mk([100.0 + i for i in range(5)]), ScalpParams()) is None
