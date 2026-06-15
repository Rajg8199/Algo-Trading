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
from tp_research.screener.signals import evaluate_breakout, scan

__all__ = [
    "BreakoutBacktestResult",
    "BreakoutParams",
    "BreakoutSignal",
    "DailyBar",
    "Trade",
    "backtest_breakout",
    "backtest_symbol",
    "evaluate_breakout",
    "scan",
    "summarize",
]
