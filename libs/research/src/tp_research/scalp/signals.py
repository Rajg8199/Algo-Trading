"""Intraday scalp signal — EMA(9/21) trend + pullback-to-fast-EMA reclaim + RSI.

Mirrors the TradingView Scalper Toolkit, price-only (index has no volume). Pure
and testable; the scheduler job feeds it 3/5-min bars built from spot ticks.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from tp_research.screener.indicators import atr, ema, rsi


@dataclass(frozen=True)
class ScalpBar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class ScalpParams:
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 7
    atr_period: int = 14
    atr_stop_mult: float = 1.0
    reward_risk: float = 1.5

    @property
    def min_bars(self) -> int:
        return max(self.ema_slow, self.atr_period, self.rsi_period) + 2


@dataclass(frozen=True)
class ScalpSignal:
    ts: datetime
    side: str  # "LONG" | "SHORT"
    price: float  # signal-bar close (reference entry)
    stop: float
    target: float
    rsi: float
    ema_fast: float
    ema_slow: float


def scalp_signal(bars: Sequence[ScalpBar], params: ScalpParams) -> ScalpSignal | None:
    """Evaluate the LATEST bar. Long: uptrend (EMA fast>slow) + this bar dipped to
    the fast EMA and closed back above it + RSI>50. Short is the mirror. None
    otherwise."""
    if len(bars) < params.min_bars:
        return None
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    today = bars[-1]

    ef = ema(closes, params.ema_fast)
    es = ema(closes, params.ema_slow)
    r = rsi(closes, params.rsi_period)
    a = atr(highs, lows, closes, params.atr_period)
    if ef is None or es is None or r is None or a is None or a <= 0:
        return None

    long_ok = ef > es and today.low <= ef and today.close > ef and r > 50
    short_ok = ef < es and today.high >= ef and today.close < ef and r < 50
    if not (long_ok or short_ok):
        return None

    if long_ok:
        stop = today.close - params.atr_stop_mult * a
        target = today.close + params.reward_risk * params.atr_stop_mult * a
        side = "LONG"
    else:
        stop = today.close + params.atr_stop_mult * a
        target = today.close - params.reward_risk * params.atr_stop_mult * a
        side = "SHORT"

    return ScalpSignal(
        ts=today.ts,
        side=side,
        price=today.close,
        stop=stop,
        target=target,
        rsi=r,
        ema_fast=ef,
        ema_slow=es,
    )
