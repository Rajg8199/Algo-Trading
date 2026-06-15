"""Scalp outcome grading + review aggregation tests."""

from __future__ import annotations

from tp_research.scalp import evaluate_outcome, summarize_review


def test_long_hits_target() -> None:
    # entry 100, stop 98, target 104; price rises through target
    outcome, exit_price, r = evaluate_outcome("LONG", 100, 98, 104, [101, 103, 105])
    assert outcome == "WIN"
    assert exit_price == 104
    assert abs(r - 2.0) < 1e-9  # (104-100)/2


def test_long_hits_stop_first() -> None:
    outcome, _, r = evaluate_outcome("LONG", 100, 98, 104, [99, 97, 105])
    assert outcome == "LOSS"
    assert abs(r + 1.0) < 1e-9  # -1R


def test_short_hits_target() -> None:
    outcome, _, r = evaluate_outcome("SHORT", 100, 102, 96, [99, 95])
    assert outcome == "WIN"
    assert abs(r - 2.0) < 1e-9  # (100-96)/2


def test_open_when_neither_hit() -> None:
    outcome, exit_price, r = evaluate_outcome("LONG", 100, 98, 104, [100.5, 101, 101.5])
    assert outcome == "OPEN"
    assert exit_price == 101.5
    assert abs(r - 0.75) < 1e-9  # (101.5-100)/2


def test_summary() -> None:
    st = summarize_review([("WIN", 2.0), ("LOSS", -1.0), ("LOSS", -1.0), ("OPEN", 0.3)])
    assert st.n == 4
    assert st.wins == 1 and st.losses == 2 and st.open == 1
    assert abs(st.hit_rate - 1 / 3) < 1e-9  # wins / decided
    assert abs(st.expectancy_r - 0.075) < 1e-9  # (2-1-1+0.3)/4


def test_summary_empty() -> None:
    st = summarize_review([])
    assert st.n == 0 and st.hit_rate is None and st.expectancy_r is None
