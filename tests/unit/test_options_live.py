"""Live options snapshot summary + formatter tests."""

from __future__ import annotations

from datetime import datetime

from tp_research.options import format_live_options, summarize_live
from tp_research.options.live import LiveOptionsSnapshot, _LiveRow

TS = datetime(2026, 6, 15, 11, 30)


def _row(strike: float, ot: str, iv: float | None, oi: float | None, ltp: float | None) -> _LiveRow:
    return _LiveRow(strike=strike, option_type=ot, iv=iv, oi=oi, ltp=ltp)


def test_summarize_picks_atm_and_computes_metrics() -> None:
    spot = 24_500.0
    rows = [
        _row(24_400, "CE", 13.0, 1000, 180), _row(24_400, "PE", 13.4, 900, 90),
        _row(24_500, "CE", 14.0, 2000, 120), _row(24_500, "PE", 14.2, 2200, 110),
        _row(24_600, "CE", 15.0, 800, 60), _row(24_600, "PE", 15.4, 700, 200),
    ]
    snap = summarize_live("NIFTY", TS, spot, rows)
    assert snap.atm_strike == 24_500
    assert abs(snap.atm_iv - 14.1) < 1e-6  # mean of 14.0 / 14.2
    assert snap.atm_straddle == 230  # 120 + 110
    # PCR = put OI / call OI = (900+2200+700)/(1000+2000+800) = 3800/3800 = 1.0
    assert abs(snap.pcr_oi - 1.0) < 1e-6
    assert snap.total_oi == 7600


def test_summarize_handles_missing_iv() -> None:
    snap = summarize_live("X", TS, 100.0, [_row(100, "CE", None, 5, 2), _row(100, "PE", None, 5, 3)])
    assert snap.atm_iv is None  # no usable IV
    assert snap.atm_straddle == 5  # ltp still sums


def test_format_live_includes_spot_vix_and_footer() -> None:
    snap = LiveOptionsSnapshot("NIFTY", TS, 24_500.0, 24_500.0, 14.1, 230.0, 0.95, 7600.0)
    msg = format_live_options({"NIFTY": snap}, india_vix=13.8, now=TS, underlyings=("NIFTY",))
    assert "Live options · 11:30" in msg
    assert "spot 24,500" in msg
    assert "ATM IV 14.1%" in msg
    assert "India VIX  13.80" in msg
    assert "NOT a trading signal" in msg


def test_format_live_missing_index() -> None:
    msg = format_live_options(
        {"NIFTY": None}, india_vix=None, now=TS, underlyings=("NIFTY", "BANKNIFTY")
    )
    assert "no live snapshot" in msg
    assert "BANKNIFTY" in msg
