"""Honest backtest of the breakout rules over daily bars.

Discipline baked in:
  - no lookahead: a signal at day t's close is entered at day t+1's OPEN,
  - realistic exits: gap-through-stop fills at the open, intraday stop at the
    stop, optional fixed target, otherwise an ATR chandelier trail,
  - round-trip costs subtracted from every trade,
  - results reported in R-multiples (size-independent) plus a fixed-fractional
    equity curve for max drawdown.

This is what makes an alert trustworthy or not — it never asserts a win rate it
hasn't measured.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from tp_research.screener.indicators import atr
from tp_research.screener.models import BreakoutParams, DailyBar
from tp_research.screener.signals import evaluate_breakout


@dataclass(frozen=True)
class Trade:
    symbol: str
    entry_idx: int
    exit_idx: int
    entry_day: date
    exit_day: date
    entry: float
    exit: float
    initial_risk: float
    r_multiple: float
    return_pct: float  # net of round-trip cost
    holding_days: int
    reason: str


@dataclass
class _OpenPos:
    entry_idx: int
    entry: float
    stop: float
    initial_risk: float
    target: float | None


@dataclass(frozen=True)
class BreakoutBacktestResult:
    n_trades: int
    wins: int
    losses: int
    win_rate: float | None
    expectancy_r: float | None  # mean R per trade — the headline honesty metric
    profit_factor: float | None
    avg_win_r: float | None
    avg_loss_r: float | None
    max_drawdown_pct: float
    total_return_pct: float
    avg_holding_days: float | None

    @property
    def acceptable(self) -> bool:
        """A deliberately strict, capital-preservation-first gate. Mirrors the
        REJECT-by-default spirit of the options side: positive edge, real
        sample, controlled drawdown — else the signals stay UNVALIDATED."""
        if self.expectancy_r is None or self.profit_factor is None or self.win_rate is None:
            return False
        return (
            self.n_trades >= 30
            and self.expectancy_r > 0.1
            and self.profit_factor > 1.3
            and self.max_drawdown_pct < 25.0
        )


def backtest_symbol(
    history: Sequence[DailyBar],
    params: BreakoutParams,
    entry_allowed: frozenset[date] | None = None,
) -> list[Trade]:
    """`entry_allowed`, when given, gates NEW entries to those dates — used for a
    market-regime filter (e.g. only enter when the broad market is in an
    uptrend). Exits are never gated."""
    trades: list[Trade] = []
    position: _OpenPos | None = None
    pending = None  # BreakoutSignal queued for next-open entry
    highs = [b.high for b in history]
    lows = [b.low for b in history]
    closes = [b.close for b in history]

    for t in range(len(history)):
        bar = history[t]

        # 1) execute a queued entry at today's open
        if position is None and pending is not None:
            entry = bar.open
            risk = entry - pending.stop
            if risk > 0:
                target = entry + params.target_r * risk if params.target_r is not None else None
                position = _OpenPos(t, entry, pending.stop, risk, target)
            pending = None

        # 2) manage an open position on today's bar (can exit the same day it opened)
        if position is not None:
            exit_price, reason = _check_exit(position, bar, highs, lows, closes, t, params)
            if exit_price is not None:
                trades.append(
                    Trade(
                        symbol=bar.symbol,
                        entry_idx=position.entry_idx,
                        exit_idx=t,
                        entry_day=history[position.entry_idx].day,
                        exit_day=bar.day,
                        entry=position.entry,
                        exit=exit_price,
                        initial_risk=position.initial_risk,
                        r_multiple=(exit_price - position.entry) / position.initial_risk,
                        return_pct=(exit_price / position.entry - 1.0) - params.cost_pct,
                        holding_days=t - position.entry_idx,
                        reason=reason,
                    )
                )
                position = None

        # 3) evaluate a fresh signal at today's close (enters next open), subject
        #    to the market-regime gate
        regime_ok = entry_allowed is None or bar.day in entry_allowed
        if position is None and pending is None and t + 1 < len(history) and regime_ok:
            sig = evaluate_breakout(history[: t + 1], params)
            if sig is not None:
                pending = sig

    # close any still-open position at the last bar's close
    if position is not None:
        last = history[-1]
        t = len(history) - 1
        trades.append(
            Trade(
                symbol=last.symbol,
                entry_idx=position.entry_idx,
                exit_idx=t,
                entry_day=history[position.entry_idx].day,
                exit_day=last.day,
                entry=position.entry,
                exit=last.close,
                initial_risk=position.initial_risk,
                r_multiple=(last.close - position.entry) / position.initial_risk,
                return_pct=(last.close / position.entry - 1.0) - params.cost_pct,
                holding_days=t - position.entry_idx,
                reason="open_at_end",
            )
        )

    return trades


def _check_exit(
    pos: _OpenPos,
    bar: DailyBar,
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    t: int,
    params: BreakoutParams,
) -> tuple[float | None, str]:
    # gap below stop → fill at the open (worse than stop, realistic)
    if bar.open <= pos.stop and t > pos.entry_idx:
        return bar.open, "gap_stop"
    # intraday stop (checked before target — conservative when both touch)
    if bar.low <= pos.stop:
        return pos.stop, "stop"
    if pos.target is not None and bar.high >= pos.target:
        return pos.target, "target"
    # otherwise raise the trailing stop (chandelier off the close)
    a = atr(highs[: t + 1], lows[: t + 1], closes[: t + 1], params.atr_period)
    if a is not None:
        pos.stop = max(pos.stop, bar.close - params.atr_stop_mult * a)
    return None, "hold"


def backtest_breakout(
    bars_by_symbol: dict[str, Sequence[DailyBar]],
    params: BreakoutParams,
    entry_allowed: frozenset[date] | None = None,
) -> BreakoutBacktestResult:
    trades: list[Trade] = []
    for history in bars_by_symbol.values():
        trades.extend(backtest_symbol(history, params, entry_allowed))
    return summarize(trades, params)


def summarize(trades: Sequence[Trade], params: BreakoutParams) -> BreakoutBacktestResult:
    n = len(trades)
    if n == 0:
        return BreakoutBacktestResult(0, 0, 0, None, None, None, None, None, 0.0, 0.0, None)

    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple <= 0]
    gross_win = sum(t.return_pct for t in wins)
    gross_loss = sum(t.return_pct for t in losses)
    profit_factor = gross_win / abs(gross_loss) if gross_loss < 0 else None

    # fixed-fractional equity curve (each trade risks risk_pct), in true exit-date
    # order so the drawdown is comparable across symbols
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.exit_day):
        equity *= 1.0 + t.r_multiple * params.risk_pct
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)

    return BreakoutBacktestResult(
        n_trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / n,
        expectancy_r=sum(t.r_multiple for t in trades) / n,
        profit_factor=profit_factor,
        avg_win_r=sum(t.r_multiple for t in wins) / len(wins) if wins else None,
        avg_loss_r=sum(t.r_multiple for t in losses) / len(losses) if losses else None,
        max_drawdown_pct=max_dd * 100.0,
        total_return_pct=(equity - 1.0) * 100.0,
        avg_holding_days=sum(t.holding_days for t in trades) / n,
    )
