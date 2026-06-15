"""Split/bonus back-adjustment tests — a real split is detected and the series
made continuous; a genuine crash that doesn't match a known factor is left
alone."""

from __future__ import annotations

from datetime import date, timedelta

from tp_research.equity.adjust import adjust_splits, detect_factor
from tp_research.screener.models import DailyBar

START = date(2025, 1, 1)


def _bars(closes: list[float], opens: list[float] | None = None) -> list[DailyBar]:
    out: list[DailyBar] = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else (closes[i - 1] if i else c)
        out.append(DailyBar("X", START + timedelta(days=i), o, max(o, c), min(o, c), c, 1000))
    return out


def test_detect_known_split() -> None:
    assert detect_factor(200.0, 100.0) == 2.0  # 1:2 split, ratio 0.5
    assert detect_factor(500.0, 100.0) == 5.0  # 1:5, ratio 0.2
    assert detect_factor(100.0, 66.7) == 1.5  # 3:2 bonus, ratio ~0.667


def test_ignores_ordinary_moves_and_unmatched_crash() -> None:
    assert detect_factor(100.0, 98.0) is None  # normal day
    assert detect_factor(100.0, 72.0) is None  # 28% crash, not near any factor


def test_back_adjusts_pre_split_prices() -> None:
    # three pre-split closes, then a 1:2 split, then two post-split closes
    closes = [200.0, 202.0, 204.0, 103.0, 104.0]
    opens = [200.0, 201.0, 203.0, 102.0, 103.0]  # split day opens at 102 (~204/2)
    adj = adjust_splits(_bars(closes, opens))
    # pre-split halved, continuous with post-split
    assert abs(adj[2].close - 102.0) < 1e-6  # 204 / 2
    assert abs(adj[0].close - 100.0) < 1e-6  # 200 / 2
    assert adj[2].volume == 2000  # pre-split volume doubled
    # post-split bars untouched
    assert adj[3].close == 103.0
    assert adj[4].volume == 1000


def test_no_split_is_identity() -> None:
    bars = _bars([100.0 + i for i in range(20)])
    assert adjust_splits(bars) == bars
