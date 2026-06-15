"""Options digest formatter tests — real fields render, missing indices degrade
to 'awaiting data', and it never reads as a trade signal."""

from __future__ import annotations

from datetime import date

from tp_research.options import format_options_digest

DAY = date(2026, 6, 12)

NIFTY_F = {
    "atm_iv_front": 14.2,
    "atm_iv_next": 13.8,
    "iv_percentile_1y": 62.0,
    "iv_rank_1y": 58.0,
    "term_slope": -0.4,
    "put_skew_25d": 1.8,
    "call_skew_25d": 1.2,
    "vov_20d": 0.93,
    "rv_yz_20d": 11.5,
    "oi_total_front": 1_200_000.0,
    "oi_change_1d": 48_000.0,
}


def test_digest_renders_real_fields() -> None:
    msg = format_options_digest({"NIFTY": (NIFTY_F, DAY)}, underlyings=("NIFTY",))
    assert "ATM IV  14.2%" in msg
    assert "next 13.8%" in msg
    assert "backwardation" in msg  # term_slope < 0
    assert "VRP +2.7" in msg  # 14.2 - 11.5
    assert "NOT a trading signal" in msg


def test_missing_index_degrades() -> None:
    msg = format_options_digest(
        {"NIFTY": (NIFTY_F, DAY)}, underlyings=("NIFTY", "SENSEX", "BANKNIFTY")
    )
    assert "awaiting data" in msg
    assert "SENSEX" in msg and "BANKNIFTY" in msg


def test_contango_label() -> None:
    f = {"atm_iv_front": 12.0, "term_slope": 0.6}
    msg = format_options_digest({"NIFTY": (f, DAY)}, underlyings=("NIFTY",))
    assert "contango" in msg
    # VRP line absent without realized vol
    assert "VRP" not in msg
