from datetime import date
from pathlib import Path

import numpy as np
import pytest
from tp_research.gfdl.bsm import bs_price, greeks_from_iv, implied_vol
from tp_research.gfdl.importer import lot_size_for
from tp_research.gfdl.parse import MappingConfig, ParseStats, TickerParser, parse_file

MAPPING = MappingConfig.load(Path("docs/data/gfdl_mapping.json"))


# ── BSM ──────────────────────────────────────────────────────────────────────
def test_iv_round_trip_recovers_known_vol() -> None:
    spot = np.full(4, 24500.0)
    strikes = np.array([24500.0, 24700.0, 24300.0, 25500.0])
    t = np.full(4, 5.0 / 365.0)
    true_vol = np.array([0.14, 0.16, 0.15, 0.22])
    is_call = np.array([True, True, False, True])
    prices = bs_price(spot, strikes, t, true_vol, is_call)
    solved = implied_vol(prices, spot, strikes, t, is_call)
    np.testing.assert_allclose(solved, true_vol, atol=1e-4)


def test_iv_unsolvable_is_nan() -> None:
    spot = np.array([24500.0, 24500.0, 24500.0])
    strikes = np.array([24000.0, 24500.0, 24500.0])
    t = np.array([5.0 / 365.0, 0.0, 5.0 / 365.0])
    is_call = np.array([True, True, True])
    # below intrinsic / expired / zero price
    prices = np.array([400.0, 100.0, 0.0])
    solved = implied_vol(prices, spot, strikes, t, is_call)
    assert np.isnan(solved).all()


def test_greeks_sane_atm() -> None:
    spot = np.array([24500.0])
    strike = np.array([24500.0])
    t = np.array([5.0 / 365.0])
    iv = np.array([0.14])
    call = greeks_from_iv(iv, spot, strike, t, np.array([True]))
    put = greeks_from_iv(iv, spot, strike, t, np.array([False]))
    assert 0.45 < call.delta[0] < 0.60  # ATM call delta slightly above 0.5 w/ rates
    assert -0.55 < put.delta[0] < -0.40
    assert call.gamma[0] > 0 and call.vega[0] > 0 and call.theta[0] < 0
    assert call.iv_pct[0] == pytest.approx(14.0)


# ── ticker parsing ───────────────────────────────────────────────────────────
def test_parses_option_future_index_tickers() -> None:
    parser = TickerParser(MAPPING)
    opt = parser.parse("NIFTY12JUN2624500CE")
    assert opt is not None and opt.kind == "OPT"
    assert opt.expiry == date(2026, 6, 12) and opt.strike == 24500.0 and opt.option_type == "CE"

    fut = parser.parse("SENSEX25JUN26FUT.BFO")
    assert fut is not None and fut.kind == "FUT" and fut.underlying == "SENSEX"

    idx = parser.parse("NIFTY 50")
    assert idx is not None and idx.kind == "INDEX" and idx.underlying == "NIFTY"

    assert parser.parse("BANKNIFTY12JUN2652000CE") is None  # out of universe
    assert parser.parse("GARBAGE") is None


def test_parse_file_counts_rejects(tmp_path: Path) -> None:
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text(
        "Ticker,Date,Time,Open,High,Low,Close,Volume,OpenInterest\n"
        "NIFTY12JUN2624500CE,11/06/2026,09:15,100,101,99,100.5,1200,50000\n"
        "UNKNOWNTICKER,11/06/2026,09:15,1,1,1,1,1,1\n"
        "NIFTY12JUN2624500CE,11/06/2026,09:16,100,101,99,0,1200,50000\n"
        "NIFTY12JUN2624500CE,badnews,09:17,100,101,99,100.5,1200,50000\n"
    )
    stats = ParseStats()
    bars = parse_file(csv_file, MAPPING, stats)
    assert len(bars) == 1
    assert stats.rows == 4 and stats.parsed == 1
    assert stats.rejected_by_reason["unmatched_ticker"] == 1
    assert stats.rejected_by_reason["nonpositive_close"] == 1


def test_lot_size_schedule() -> None:
    assert lot_size_for("NIFTY", date(2024, 6, 1)) == 50
    assert lot_size_for("NIFTY", date(2025, 1, 1)) == 75
    assert lot_size_for("SENSEX", date(2025, 1, 1)) == 20
    assert lot_size_for("NIFTY", None) == 50
