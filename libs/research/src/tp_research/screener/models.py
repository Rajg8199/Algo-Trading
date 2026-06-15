"""Value types for the equity breakout scanner.

Deliberately tiny and IO-free: a `DailyBar` is one symbol on one trading day,
`BreakoutParams` is the (pre-registerable) rule set, and `BreakoutSignal` is a
single objective entry candidate with its risk geometry already resolved. No
part of this package promises a signal will win — a signal is a rule match,
nothing more. Sizing and stops are first-class so capital preservation is
structural, not advisory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class BreakoutParams:
    """Donchian/Turtle-style long breakout with a trend filter, a volume
    confirmation, and an ATR-based stop. Defaults are conservative; the grid is
    meant to be backtested and pre-registered before any alert is trusted."""

    breakout_lookback: int = 20  # close must exceed the high of the prior N days
    trend_fast: int = 50  # SMA fast — uptrend filter
    trend_slow: int = 200  # SMA slow — uptrend filter
    volume_lookback: int = 20
    volume_mult: float = 1.5  # today's volume must exceed mult x its average
    atr_period: int = 14
    atr_stop_mult: float = 2.0  # initial (and trailing) stop = price - mult x ATR
    target_r: float | None = None  # optional fixed take-profit in R; None = trail only
    risk_pct: float = 0.01  # fraction of capital risked per trade
    cost_pct: float = 0.002  # round-trip cost (brokerage+STT+slippage) as fraction
    require_trend: bool = True

    @property
    def min_history(self) -> int:
        """Bars needed before a signal can even be evaluated."""
        return (
            max(self.breakout_lookback, self.trend_slow, self.volume_lookback, self.atr_period) + 1
        )


@dataclass(frozen=True)
class BreakoutSignal:
    symbol: str
    day: date
    entry: float  # reference price = breakout-day close (live entry is next-open)
    stop: float
    target: float | None
    atr: float
    donchian_high: float
    sma_fast: float | None
    sma_slow: float | None
    volume_ratio: float  # today's volume / its average
    risk_per_share: float

    def position_size(self, capital: float, risk_pct: float) -> int:
        """Shares such that (entry - stop) loss equals risk_pct of capital.
        Returns 0 when the stop is degenerate — never divides by zero."""
        if self.risk_per_share <= 0:
            return 0
        return math.floor((capital * risk_pct) / self.risk_per_share)
