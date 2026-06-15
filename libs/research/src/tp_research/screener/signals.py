"""Breakout signal evaluation — the objective rule check, no discretion.

`evaluate_breakout` looks only at history up to and including the candidate day
(no lookahead) and returns a signal iff ALL conditions hold:
  1. close > highest high of the prior `breakout_lookback` days (Donchian),
  2. (optional) uptrend: close > SMA_slow and SMA_fast > SMA_slow,
  3. volume > `volume_mult` x its `volume_lookback` average,
  4. a usable ATR exists so a real stop can be placed.
"""

from __future__ import annotations

from collections.abc import Sequence

from tp_research.screener.indicators import atr, highest, sma
from tp_research.screener.models import BreakoutParams, BreakoutSignal, DailyBar


def evaluate_breakout(history: Sequence[DailyBar], params: BreakoutParams) -> BreakoutSignal | None:
    """`history` is one symbol's bars in chronological order; the LAST bar is the
    candidate day. Returns a signal or None."""
    if len(history) < params.min_history:
        return None

    today = history[-1]
    prior = history[:-1]

    prior_highs = [b.high for b in prior]
    donchian_high = highest(prior_highs, params.breakout_lookback)
    if donchian_high is None or today.close <= donchian_high:
        return None

    closes = [b.close for b in history]
    sma_fast = sma(closes, params.trend_fast)
    sma_slow = sma(closes, params.trend_slow)
    if params.require_trend:
        if sma_fast is None or sma_slow is None:
            return None
        if not (today.close > sma_slow and sma_fast > sma_slow):
            return None

    prior_vols = [b.volume for b in prior]
    avg_vol = sum(prior_vols[-params.volume_lookback :]) / params.volume_lookback
    if avg_vol <= 0 or today.volume < params.volume_mult * avg_vol:
        return None
    volume_ratio = today.volume / avg_vol

    a = atr([b.high for b in history], [b.low for b in history], closes, params.atr_period)
    if a is None or a <= 0:
        return None

    stop = today.close - params.atr_stop_mult * a
    risk_per_share = today.close - stop
    if risk_per_share <= 0:
        return None
    target = today.close + params.target_r * risk_per_share if params.target_r is not None else None

    return BreakoutSignal(
        symbol=today.symbol,
        day=today.day,
        entry=today.close,
        stop=stop,
        target=target,
        atr=a,
        donchian_high=donchian_high,
        sma_fast=sma_fast,
        sma_slow=sma_slow,
        volume_ratio=volume_ratio,
        risk_per_share=risk_per_share,
    )


def scan(
    bars_by_symbol: dict[str, Sequence[DailyBar]], params: BreakoutParams
) -> list[BreakoutSignal]:
    """Evaluate every symbol's latest bar; return firing signals, strongest
    volume confirmation first (a proxy for conviction, not a guarantee)."""
    signals: list[BreakoutSignal] = []
    for history in bars_by_symbol.values():
        sig = evaluate_breakout(history, params)
        if sig is not None:
            signals.append(sig)
    signals.sort(key=lambda s: s.volume_ratio, reverse=True)
    return signals
