"""Volatility and market estimators. Pure functions over numpy arrays —
no I/O, no DB, fully unit-testable with known-value fixtures.

Conventions:
- inputs are daily OHLC arrays, oldest first
- all vols are annualized percentages (e.g. 14.2 = 14.2% annualized)
- functions return None when there is not enough data, never a fake number
"""

import math

import numpy as np
from numpy.typing import NDArray

TRADING_DAYS = 252
ANN = math.sqrt(TRADING_DAYS)

FloatArray = NDArray[np.float64]


def log_returns(closes: FloatArray) -> FloatArray:
    return np.diff(np.log(closes))


def rv_close_close(closes: FloatArray, window: int = 20) -> float | None:
    """Classic close-close realized vol over the trailing window."""
    returns = log_returns(closes)
    if len(returns) < window:
        return None
    tail = returns[-window:]
    return float(np.std(tail, ddof=1) * ANN * 100)


def rv_parkinson(highs: FloatArray, lows: FloatArray, window: int = 20) -> float | None:
    """Parkinson range estimator: uses high/low, ~5x more efficient than CC,
    but ignores overnight gaps (understates total vol in gappy markets)."""
    if len(highs) < window or len(lows) < window:
        return None
    hl = np.log(highs[-window:] / lows[-window:])
    var = float(np.mean(hl**2)) / (4 * math.log(2))
    return math.sqrt(var * TRADING_DAYS) * 100


def rv_yang_zhang(
    opens: FloatArray,
    highs: FloatArray,
    lows: FloatArray,
    closes: FloatArray,
    window: int = 20,
) -> float | None:
    """Yang-Zhang: combines overnight, open-close, and Rogers-Satchell terms.
    The right default for Indian indices where overnight gaps carry real vol."""
    n = window
    if min(len(opens), len(highs), len(lows), len(closes)) < n + 1:
        return None
    o, h, lo, c = (arr[-(n + 1) :] for arr in (opens, highs, lows, closes))

    overnight = np.log(o[1:] / c[:-1])
    open_close = np.log(c[1:] / o[1:])
    var_on = float(np.var(overnight, ddof=1))
    var_oc = float(np.var(open_close, ddof=1))

    hh, ll, cc, oo = h[1:], lo[1:], c[1:], o[1:]
    rs = np.log(hh / cc) * np.log(hh / oo) + np.log(ll / cc) * np.log(ll / oo)
    var_rs = float(np.mean(rs))

    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    var = var_on + k * var_oc + (1 - k) * var_rs
    if var <= 0:
        return None
    return math.sqrt(var * TRADING_DAYS) * 100


def har_rv_forecast(daily_rv: FloatArray, min_obs: int = 60) -> float | None:
    """HAR-RV (Corsi 2009): RV_{t+1} = b0 + b1*RV_d + b2*RV_w + b3*RV_m + e.

    daily_rv: series of daily realized vols (annualized %), oldest first.
    Fits OLS on the trailing history and returns the one-day-ahead forecast.
    """
    rv = np.asarray(daily_rv, dtype=np.float64)
    if len(rv) < min_obs:
        return None
    # Build regressors: daily, weekly (5d mean), monthly (22d mean)
    n = len(rv)
    rows = []
    targets = []
    for t in range(22, n - 1):
        rows.append(
            [1.0, rv[t], float(np.mean(rv[t - 4 : t + 1])), float(np.mean(rv[t - 21 : t + 1]))]
        )
        targets.append(rv[t + 1])
    x = np.asarray(rows)
    y = np.asarray(targets)
    if len(y) < 30:
        return None
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    latest = np.asarray([1.0, rv[-1], float(np.mean(rv[-5:])), float(np.mean(rv[-22:]))])
    forecast = float(latest @ beta)
    # A vol forecast below zero or wildly above history is a fit artifact.
    if forecast <= 0 or forecast > float(np.max(rv)) * 3:
        return None
    return forecast


def vol_of_vol(iv_series: FloatArray, window: int = 20) -> float | None:
    """Stdev of daily IV changes (vol points) over the window — the regime
    gate input: high vol-of-vol marks regimes where short-premium dies."""
    iv = np.asarray(iv_series, dtype=np.float64)
    if len(iv) < window + 1:
        return None
    changes = np.diff(iv)[-window:]
    return float(np.std(changes, ddof=1))


def atr(highs: FloatArray, lows: FloatArray, closes: FloatArray, window: int = 14) -> float | None:
    """Average True Range (Wilder), in index points."""
    if min(len(highs), len(lows), len(closes)) < window + 1:
        return None
    h, lo, c = highs[-(window + 1) :], lows[-(window + 1) :], closes[-(window + 1) :]
    tr = np.maximum(h[1:] - lo[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(lo[1:] - c[:-1])))
    return float(np.mean(tr))


def percentile_rank(series: FloatArray, value: float) -> float | None:
    """Percentile of `value` within `series` (0-100)."""
    arr = np.asarray(series, dtype=np.float64)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 20:
        return None
    return float(100.0 * np.mean(arr <= value))


def iv_rank(series: FloatArray, value: float) -> float | None:
    """IV rank: where value sits between the min and max of the lookback (0-100).
    Distinct from percentile — rank is range-based, percentile is count-based."""
    arr = np.asarray(series, dtype=np.float64)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 20:
        return None
    lo, hi = float(np.min(arr)), float(np.max(arr))
    if hi - lo < 1e-9:
        return None
    return float(100.0 * (value - lo) / (hi - lo))
