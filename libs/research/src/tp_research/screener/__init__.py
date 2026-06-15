"""Equity breakout scanner — objective Donchian/Turtle-style long signals with
a trend filter, volume confirmation, ATR risk geometry, and an honest backtest.
No signal is a guarantee; the backtest is what earns (or denies) trust."""

from tp_research.screener.backtest import (
    BreakoutBacktestResult,
    Trade,
    backtest_breakout,
    backtest_symbol,
    summarize,
)
from tp_research.screener.models import BreakoutParams, BreakoutSignal, DailyBar
from tp_research.screener.momentum import (
    MomentumParams,
    PortfolioResult,
    backtest_momentum,
    current_picks,
)
from tp_research.screener.signals import evaluate_breakout, scan

__all__ = [
    "BreakoutBacktestResult",
    "BreakoutParams",
    "BreakoutSignal",
    "DailyBar",
    "MomentumParams",
    "PortfolioResult",
    "Trade",
    "backtest_breakout",
    "backtest_momentum",
    "backtest_symbol",
    "current_picks",
    "evaluate_breakout",
    "scan",
    "summarize",
]
