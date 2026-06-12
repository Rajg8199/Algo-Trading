"""Vectorized Black-Scholes for import-time enrichment.

GFDL 1-min bars carry no IV/Greeks; we compute them from option close vs
same-minute spot. European cash-settled index options — BS is the right
model. IV solved by bisection (vectorized, 64 iterations, [0.5%, 500%]).

Rows where no IV exists (price below intrinsic, expired, missing spot)
get NaN — downstream stores NULL, never a fabricated number.
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

TRADING_MINUTES_PER_YEAR = 252.0 * 375.0
RISK_FREE_RATE = 0.065  # config-reviewed quarterly; documented in import report


def norm_cdf(x: FloatArray) -> FloatArray:
    # vectorized erf via np.vectorize is slow; use the Abramowitz-Stegun 7.1.26
    # rational approximation (|err| < 1.5e-7 — far below IV solver tolerance)
    sign = np.sign(x)
    z = np.abs(x) / math.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * z)
    poly = t * (
        0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))
    )
    erf_z = 1.0 - poly * np.exp(-z * z)
    return 0.5 * (1.0 + sign * erf_z)


def bs_price(
    spot: FloatArray,
    strike: FloatArray,
    t_years: FloatArray,
    vol: FloatArray,
    is_call: NDArray[np.bool_],
    rate: float = RISK_FREE_RATE,
) -> FloatArray:
    t = np.maximum(t_years, 1e-9)
    v = np.maximum(vol, 1e-9)
    sqrt_t = np.sqrt(t)
    d1 = (np.log(spot / strike) + (rate + 0.5 * v * v) * t) / (v * sqrt_t)
    d2 = d1 - v * sqrt_t
    call = spot * norm_cdf(d1) - strike * np.exp(-rate * t) * norm_cdf(d2)
    put = strike * np.exp(-rate * t) * norm_cdf(-d2) - spot * norm_cdf(-d1)
    return np.where(is_call, call, put)


def implied_vol(
    price: FloatArray,
    spot: FloatArray,
    strike: FloatArray,
    t_years: FloatArray,
    is_call: NDArray[np.bool_],
    rate: float = RISK_FREE_RATE,
    iterations: int = 64,
) -> FloatArray:
    """Bisection on [0.005, 5.0]. Returns NaN where unsolvable."""
    intrinsic = np.where(
        is_call,
        np.maximum(spot - strike * np.exp(-rate * np.maximum(t_years, 0)), 0.0),
        np.maximum(strike * np.exp(-rate * np.maximum(t_years, 0)) - spot, 0.0),
    )
    solvable = (price > intrinsic + 1e-6) & (t_years > 1e-6) & (spot > 0) & (price > 0)

    lo = np.full_like(price, 0.005)
    hi = np.full_like(price, 5.0)
    for _ in range(iterations):
        mid = (lo + hi) / 2
        mid_price = bs_price(spot, strike, t_years, mid, is_call, rate)
        too_high = mid_price > price
        hi = np.where(too_high, mid, hi)
        lo = np.where(too_high, lo, mid)
    iv = (lo + hi) / 2
    # Reject boundary solutions: price outside the model's reachable range.
    at_bounds = (iv <= 0.006) | (iv >= 4.99)
    return np.where(solvable & ~at_bounds, iv, np.nan)


@dataclass(frozen=True)
class Greeks:
    iv_pct: FloatArray  # IV in percent (matches option_chain.iv convention)
    delta: FloatArray
    gamma: FloatArray
    theta: FloatArray  # per calendar day
    vega: FloatArray  # per vol point


def greeks_from_iv(
    iv: FloatArray,
    spot: FloatArray,
    strike: FloatArray,
    t_years: FloatArray,
    is_call: NDArray[np.bool_],
    rate: float = RISK_FREE_RATE,
) -> Greeks:
    t = np.maximum(t_years, 1e-9)
    v = np.where(np.isnan(iv), 1e-9, np.maximum(iv, 1e-9))
    sqrt_t = np.sqrt(t)
    d1 = (np.log(spot / strike) + (rate + 0.5 * v * v) * t) / (v * sqrt_t)
    d2 = d1 - v * sqrt_t
    pdf_d1 = np.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)

    delta = np.where(is_call, norm_cdf(d1), norm_cdf(d1) - 1.0)
    gamma = pdf_d1 / (spot * v * sqrt_t)
    vega = spot * pdf_d1 * sqrt_t / 100.0
    theta_call = (
        -spot * pdf_d1 * v / (2 * sqrt_t) - rate * strike * np.exp(-rate * t) * norm_cdf(d2)
    ) / 365.0
    theta_put = (
        -spot * pdf_d1 * v / (2 * sqrt_t) + rate * strike * np.exp(-rate * t) * norm_cdf(-d2)
    ) / 365.0

    nan_mask = np.isnan(iv)

    def blank(arr: FloatArray) -> FloatArray:
        return np.where(nan_mask, np.nan, arr)

    return Greeks(
        iv_pct=iv * 100.0,
        delta=blank(delta),
        gamma=blank(gamma),
        theta=blank(np.where(is_call, theta_call, theta_put)),
        vega=blank(vega),
    )
