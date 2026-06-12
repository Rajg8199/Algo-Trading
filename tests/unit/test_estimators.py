import math

import numpy as np
import pytest
from tp_research import estimators as est

RNG = np.random.default_rng(42)


def synthetic_prices(n: int = 300, daily_vol: float = 0.01) -> np.ndarray:
    """GBM-ish closes with known daily vol."""
    returns = RNG.normal(0, daily_vol, n)
    return 24000 * np.exp(np.cumsum(returns))


def test_rv_close_close_recovers_known_vol() -> None:
    closes = synthetic_prices(n=500, daily_vol=0.01)
    rv = est.rv_close_close(closes, window=400)
    assert rv is not None
    expected = 0.01 * math.sqrt(252) * 100  # ≈ 15.87
    assert rv == pytest.approx(expected, rel=0.15)


def test_rv_insufficient_data_returns_none() -> None:
    assert est.rv_close_close(np.array([100.0, 101.0]), window=20) is None
    assert est.har_rv_forecast(np.full(10, 14.0)) is None
    assert est.vol_of_vol(np.array([14.0, 15.0]), window=20) is None


def test_parkinson_on_constant_range() -> None:
    # H/L ratio constant -> deterministic Parkinson vol
    highs = np.full(30, 24100.0)
    lows = np.full(30, 24000.0)
    rv = est.rv_parkinson(highs, lows, window=20)
    assert rv is not None
    hl = math.log(24100 / 24000)
    expected = math.sqrt(hl**2 / (4 * math.log(2)) * 252) * 100
    assert rv == pytest.approx(expected, rel=1e-9)


def test_yang_zhang_positive_and_sane() -> None:
    closes = synthetic_prices(100, 0.012)
    opens = closes * (1 + RNG.normal(0, 0.004, 100))
    highs = np.maximum(opens, closes) * 1.004
    lows = np.minimum(opens, closes) * 0.996
    rv = est.rv_yang_zhang(opens, highs, lows, closes)
    assert rv is not None
    assert 5.0 < rv < 60.0


def test_har_rv_forecast_tracks_persistent_vol() -> None:
    # Stationary vol around 14 -> forecast should be near 14, not at extremes
    rv_series = 14.0 + RNG.normal(0, 1.0, 200)
    forecast = est.har_rv_forecast(rv_series)
    assert forecast is not None
    assert forecast == pytest.approx(14.0, abs=2.5)


def test_atr_known_value() -> None:
    closes = np.full(20, 100.0)
    highs = np.full(20, 102.0)
    lows = np.full(20, 98.0)
    value = est.atr(highs, lows, closes, window=14)
    assert value == pytest.approx(4.0)  # TR = high-low = 4 every day


def test_percentile_and_rank() -> None:
    series = np.arange(1.0, 101.0)  # 1..100
    assert est.percentile_rank(series, 100.0) == pytest.approx(100.0)
    assert est.percentile_rank(series, 50.0) == pytest.approx(50.0)
    assert est.iv_rank(series, 50.5) == pytest.approx(50.0, abs=0.6)
    assert est.iv_rank(np.full(30, 14.0), 14.0) is None  # flat range -> undefined


def test_vol_of_vol() -> None:
    iv = np.array([14.0] * 10 + [14.0, 15.0] * 10)  # alternating ±1 changes
    vov = est.vol_of_vol(iv, window=10)
    assert vov is not None
    assert 0.9 < vov < 1.2
