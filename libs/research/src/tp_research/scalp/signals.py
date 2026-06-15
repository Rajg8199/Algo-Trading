"""Intraday scalp signal — trend-regime + pullback reclaim + momentum/vol filters.

Price-only (index has no volume). Tuned for fewer, higher-quality cues, not
optimised against data (no intraday history exists). Filters target the known
scalp failure modes:
  - chop:        EMA fast>slow AND EMA-slow sloping the right way (regime),
  - chasing:     RSI in a momentum band, NOT already extended,
  - dead tape:   ATR/price above a floor (enough range to clear costs),
  - weak bar:    signal bar closes in the upper/lower part of its range.
Still UNVALIDATED — a human cue, not an edge.
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
    slope_lookback: int = 3  # EMA-slow must be rising/falling over this many bars
    rsi_period: int = 7
    rsi_mid: float = 50.0
    rsi_extended_long: float = 78.0  # don't buy if RSI already above this
    rsi_extended_short: float = 22.0  # don't sell if RSI already below this
    atr_period: int = 14
    atr_stop_mult: float = 1.0
    reward_risk: float = 1.5
    min_atr_pct: float = 0.0006  # skip if ATR < 0.06% of price (too quiet to scalp)
    close_frac: float = 0.5  # signal bar must close in the top/bottom this fraction
    require_slope: bool = True

    @property
    def min_bars(self) -> int:
        return max(self.ema_slow + self.slope_lookback, self.atr_period, self.rsi_period) + 2


@dataclass(frozen=True)
class ScalpSignal:
    ts: datetime
    side: str  # "LONG" | "SHORT"
    price: float
    stop: float
    target: float
    rsi: float
    ema_fast: float
    ema_slow: float


def scalp_signal(bars: Sequence[ScalpBar], params: ScalpParams) -> ScalpSignal | None:
    """Evaluate the LATEST bar; return a signal or None."""
    if len(bars) < params.min_bars:
        return None
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    bar = bars[-1]

    ef = ema(closes, params.ema_fast)
    es = ema(closes, params.ema_slow)
    es_prev = ema(closes[: -params.slope_lookback], params.ema_slow)
    r = rsi(closes, params.rsi_period)
    a = atr(highs, lows, closes, params.atr_period)
    if ef is None or es is None or es_prev is None or r is None or a is None or a <= 0:
        return None

    # volatility floor — no point scalping a dead tape
    if bar.close <= 0 or a / bar.close < params.min_atr_pct:
        return None

    rng = bar.high - bar.low
    close_pos = (bar.close - bar.low) / rng if rng > 0 else 0.5  # 1=top of bar, 0=bottom

    slope_up = (not params.require_slope) or es > es_prev
    slope_dn = (not params.require_slope) or es < es_prev

    long_ok = (
        ef > es
        and slope_up
        and bar.low <= ef
        and bar.close > ef
        and params.rsi_mid < r < params.rsi_extended_long
        and close_pos >= params.close_frac
    )
    short_ok = (
        ef < es
        and slope_dn
        and bar.high >= ef
        and bar.close < ef
        and params.rsi_extended_short < r < params.rsi_mid
        and close_pos <= (1.0 - params.close_frac)
    )
    if not (long_ok or short_ok):
        return None

    risk = params.atr_stop_mult * a
    if long_ok:
        return ScalpSignal(bar.ts, "LONG", bar.close, bar.close - risk,
                           bar.close + params.reward_risk * risk, r, ef, es)
    return ScalpSignal(bar.ts, "SHORT", bar.close, bar.close + risk,
                       bar.close - params.reward_risk * risk, r, ef, es)
