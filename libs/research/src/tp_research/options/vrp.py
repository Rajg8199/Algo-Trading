"""Volatility-Risk-Premium measurement study.

The foundational question before any short-vol strategy: does ATM implied vol
systematically exceed SUBSEQUENT realized vol on NIFTY, by how much, and is the
premium bigger when IV is high? VRP_t = ATM_IV(t) - realized_vol[t, t+horizon].
A persistently positive VRP with a decent hit rate is the harvestable edge;
this just measures it honestly — no strategy, no claim.

Pure compute (this module) is separated from the DB load so it is testable.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date

ANNUALIZE = math.sqrt(252.0)


@dataclass(frozen=True)
class VrpPoint:
    day: date
    iv: float  # ATM IV, annualised vol %
    fwd_rv: float  # forward realised vol over the horizon, annualised %
    vrp: float  # iv - fwd_rv (vol points)


@dataclass(frozen=True)
class VrpSummary:
    n: int
    mean_vrp: float
    median_vrp: float
    hit_rate: float  # fraction of days IV > forward RV (premium positive)
    mean_iv: float
    mean_fwd_rv: float
    info_ratio: float  # mean / std of the daily VRP series — signal quality
    by_iv_tercile: list[tuple[str, int, float]]  # (label, n, mean_vrp)


def forward_realized_vol(closes: list[float], i: int, horizon: int) -> float | None:
    """Annualised realised vol of log returns over (i, i+horizon]. None if not
    enough forward bars."""
    if i + horizon >= len(closes):
        return None
    rets = [
        math.log(closes[j + 1] / closes[j])
        for j in range(i, i + horizon)
        if closes[j] > 0 and closes[j + 1] > 0
    ]
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * ANNUALIZE * 100.0


def compute_vrp(
    calendar: list[tuple[date, float]], iv_by_day: dict[date, float], horizon: int = 5
) -> list[VrpPoint]:
    """`calendar` = full (date, close) series oldest-first; `iv_by_day` = ATM IV
    per date. Emits a point for each day that has an IV and `horizon` future
    closes."""
    closes = [c for _, c in calendar]
    points: list[VrpPoint] = []
    for i, (day, _) in enumerate(calendar):
        iv = iv_by_day.get(day)
        if iv is None or not (1.0 < iv < 200.0):
            continue
        fwd = forward_realized_vol(closes, i, horizon)
        if fwd is None:
            continue
        points.append(VrpPoint(day, iv, fwd, iv - fwd))
    return points


def summarize_vrp(points: list[VrpPoint]) -> VrpSummary | None:
    if len(points) < 10:
        return None
    vrps = [p.vrp for p in points]
    mean_vrp = statistics.mean(vrps)
    std = statistics.pstdev(vrps)
    ordered = sorted(points, key=lambda p: p.iv)
    third = len(ordered) // 3
    buckets = [
        ("low-IV", ordered[:third]),
        ("mid-IV", ordered[third : 2 * third]),
        ("high-IV", ordered[2 * third :]),
    ]
    by_tercile = [
        (label, len(b), statistics.mean([p.vrp for p in b]) if b else 0.0) for label, b in buckets
    ]
    return VrpSummary(
        n=len(points),
        mean_vrp=mean_vrp,
        median_vrp=statistics.median(vrps),
        hit_rate=sum(1 for v in vrps if v > 0) / len(vrps),
        mean_iv=statistics.mean([p.iv for p in points]),
        mean_fwd_rv=statistics.mean([p.fwd_rv for p in points]),
        info_ratio=mean_vrp / std if std > 0 else 0.0,
        by_iv_tercile=by_tercile,
    )
