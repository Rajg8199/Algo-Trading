"""Grade emitted scalp signals against what price actually did — the honest
forward-test. Pure: given a signal and the subsequent index prices, decide
WIN (target hit first) / LOSS (stop first) / OPEN (neither by session end) and
the realized R. No claim of edge — this measures it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def _r(side: str, entry: float, exit_price: float, risk: float) -> float:
    pnl = (exit_price - entry) if side == "LONG" else (entry - exit_price)
    return pnl / risk


def evaluate_outcome(
    side: str, entry: float, stop: float, target: float, ltps: Sequence[float]
) -> tuple[str, float, float]:
    """Walk subsequent prices in order; return (outcome, exit_price, r_multiple).
    Stop is checked before target on the same price (conservative)."""
    risk = abs(entry - stop)
    if risk <= 0:
        return ("OPEN", entry, 0.0)
    for p in ltps:
        if side == "LONG":
            if p <= stop:
                return ("LOSS", stop, _r(side, entry, stop, risk))
            if p >= target:
                return ("WIN", target, _r(side, entry, target, risk))
        else:
            if p >= stop:
                return ("LOSS", stop, _r(side, entry, stop, risk))
            if p <= target:
                return ("WIN", target, _r(side, entry, target, risk))
    last = ltps[-1] if ltps else entry
    return ("OPEN", last, _r(side, entry, last, risk))


@dataclass(frozen=True)
class ReviewStats:
    n: int
    wins: int
    losses: int
    open: int
    hit_rate: float | None  # wins / (wins+losses)
    expectancy_r: float | None  # mean realized R over all graded signals


def summarize_review(outcomes: Sequence[tuple[str, float]]) -> ReviewStats:
    """`outcomes` = (outcome, r_multiple) pairs."""
    n = len(outcomes)
    if n == 0:
        return ReviewStats(0, 0, 0, 0, None, None)
    wins = sum(1 for o, _ in outcomes if o == "WIN")
    losses = sum(1 for o, _ in outcomes if o == "LOSS")
    opens = sum(1 for o, _ in outcomes if o == "OPEN")
    decided = wins + losses
    return ReviewStats(
        n=n,
        wins=wins,
        losses=losses,
        open=opens,
        hit_rate=(wins / decided) if decided else None,
        expectancy_r=sum(r for _, r in outcomes) / n,
    )
