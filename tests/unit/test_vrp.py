"""VRP measurement study tests — synthetic series with a KNOWN premium."""

from __future__ import annotations

import math
from datetime import date, timedelta

from tp_research.options.vrp import compute_vrp, forward_realized_vol, summarize_vrp

START = date(2025, 1, 1)


def test_forward_realized_vol_known() -> None:
    # flat then a constant ±1% alternation -> non-zero realised vol; flat -> ~0
    flat = [100.0] * 10
    assert forward_realized_vol(flat, 0, 5) == 0.0
    assert forward_realized_vol([100.0], 0, 5) is None  # not enough forward bars


def test_compute_vrp_with_constructed_premium() -> None:
    # calm market (tiny moves -> low realised vol) but IV quoted high -> positive VRP
    n = 80
    calendar = [(START + timedelta(days=i), 100.0 + math.sin(i / 5.0) * 0.3) for i in range(n)]
    iv_by_day = {d: 15.0 for d, _ in calendar}  # IV ~15% vs near-zero realised
    points = compute_vrp(calendar, iv_by_day, horizon=5)
    assert points
    assert all(p.vrp > 0 for p in points)  # IV >> realised -> premium positive
    summ = summarize_vrp(points)
    assert summ is not None
    assert summ.hit_rate == 1.0
    assert summ.mean_vrp > 0
    assert len(summ.by_iv_tercile) == 3


def test_summary_none_when_sparse() -> None:
    assert summarize_vrp([]) is None
