"""Short-term mean-reversion (Connors-style) — a genuinely different edge from
the breakout/momentum (which both failed). Thesis: in an UPtrend, buy oversold
dips and sell the bounce. The 2024-26 chop that whipsawed breakouts is exactly
where mean-reversion is supposed to earn. No edge assumed — the gate + the
walk-forward period breakdown decide. Reuses Trade/summarize from backtest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from tp_research.screener.backtest import BreakoutBacktestResult, Trade, summarize
from tp_research.screener.indicators import atr, rsi, sma
from tp_research.screener.models import BreakoutParams, DailyBar


@dataclass(frozen=True)
class MeanRevParams:
    trend_sma: int = 200  # only buy dips in an uptrend
    rsi_period: int = 2  # Connors short RSI
    rsi_entry: float = 10.0  # oversold threshold
    exit_sma: int = 5  # exit when close reclaims this MA (the bounce)
    max_hold: int = 10  # time stop (trading days)
    atr_period: int = 14
    atr_stop_mult: float = 3.0  # wide disaster stop
    risk_pct: float = 0.01
    cost_pct: float = 0.002

    @property
    def min_history(self) -> int:
        return max(self.trend_sma, self.atr_period, self.rsi_period) + 1


@dataclass
class _Pos:
    entry_idx: int
    entry_day: date
    entry: float
    stop: float
    initial_risk: float


def _entry_signal(history: Sequence[DailyBar], params: MeanRevParams) -> float | None:
    """Returns the stop price if today is an entry (oversold dip in an uptrend),
    else None."""
    closes = [b.close for b in history]
    trend = sma(closes, params.trend_sma)
    r = rsi(closes, params.rsi_period)
    if trend is None or r is None:
        return None
    if not (closes[-1] > trend and r < params.rsi_entry):
        return None
    a = atr([b.high for b in history], [b.low for b in history], closes, params.atr_period)
    if a is None or a <= 0:
        return None
    stop = closes[-1] - params.atr_stop_mult * a
    return stop if stop < closes[-1] else None


def backtest_meanrev_symbol(history: Sequence[DailyBar], params: MeanRevParams) -> list[Trade]:
    trades: list[Trade] = []
    position: _Pos | None = None
    pending_stop: float | None = None
    pending_exit = False
    closes = [b.close for b in history]

    for t in range(len(history)):
        bar = history[t]

        # execute queued entry at today's open
        if position is None and pending_stop is not None:
            entry = bar.open
            risk = entry - pending_stop
            if risk > 0:
                position = _Pos(t, bar.day, entry, pending_stop, risk)
            pending_stop = None

        # execute queued exit at today's open (bounce / time stop)
        if position is not None and pending_exit:
            trades.append(_close(position, bar, t, bar.open, "signal", params))
            position = None
            pending_exit = False

        # manage open position: hard stop intraday, else evaluate exit at close
        if position is not None:
            if bar.low <= position.stop:
                trades.append(_close(position, bar, t, position.stop, "stop", params))
                position = None
            else:
                held = t - position.entry_idx
                exit_ma = sma(closes[: t + 1], params.exit_sma)
                if held >= params.max_hold or (exit_ma is not None and bar.close > exit_ma):
                    pending_exit = True

        # entry signal at today's close -> next-open entry
        if position is None and pending_stop is None and t + 1 < len(history):
            pending_stop = _entry_signal(history[: t + 1], params)

    if position is not None:
        last = history[-1]
        trades.append(_close(position, last, len(history) - 1, last.close, "open_at_end", params))
    return trades


def _close(
    pos: _Pos, bar: DailyBar, t: int, exit_price: float, reason: str, p: MeanRevParams
) -> Trade:
    return Trade(
        symbol=bar.symbol,
        entry_idx=pos.entry_idx,
        exit_idx=t,
        entry_day=pos.entry_day,
        exit_day=bar.day,
        entry=pos.entry,
        exit=exit_price,
        initial_risk=pos.initial_risk,
        r_multiple=(exit_price - pos.entry) / pos.initial_risk,
        return_pct=(exit_price / pos.entry - 1.0) - p.cost_pct,
        holding_days=t - pos.entry_idx,
        reason=reason,
    )


def backtest_meanrev(
    bars_by_symbol: dict[str, Sequence[DailyBar]], params: MeanRevParams
) -> tuple[list[Trade], BreakoutBacktestResult]:
    """R-based metrics are strategy-agnostic, so we reuse `summarize`."""
    trades: list[Trade] = []
    for hist in bars_by_symbol.values():
        trades.extend(backtest_meanrev_symbol(hist, params))
    return trades, summarize(trades, BreakoutParams(risk_pct=params.risk_pct))
