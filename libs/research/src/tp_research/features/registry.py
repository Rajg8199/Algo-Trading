"""The feature registry: every persisted feature is defined here, once,
with a version. Changing a formula REQUIRES bumping the version — old values
stay queryable under the old version, which is what makes research replayable.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from tp_research import estimators as est
from tp_research.chain import atm_iv, skew_metrics, total_oi
from tp_research.features.context import FeatureContext


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    version: str
    group: str  # vol | term | skew | market | flow | participant
    fn: Callable[[FeatureContext], float | None]
    description: str


def _need_bars(ctx: FeatureContext, days: int) -> bool:
    return ctx.bars is not None and ctx.bars.days >= days


# ── volatility ───────────────────────────────────────────────────────────────
def rv_cc_20d(ctx: FeatureContext) -> float | None:
    if not _need_bars(ctx, 21):
        return None
    bars = ctx.bars
    assert bars is not None
    return est.rv_close_close(bars.closes)


def rv_pk_20d(ctx: FeatureContext) -> float | None:
    if not _need_bars(ctx, 21):
        return None
    bars = ctx.bars
    assert bars is not None
    return est.rv_parkinson(bars.highs, bars.lows)


def rv_yz_20d(ctx: FeatureContext) -> float | None:
    if not _need_bars(ctx, 22):
        return None
    bars = ctx.bars
    assert bars is not None
    return est.rv_yang_zhang(bars.opens, bars.highs, bars.lows, bars.closes)


def har_rv_forecast_1d(ctx: FeatureContext) -> float | None:
    """HAR-RV one-day-ahead forecast on a Parkinson daily-RV series
    (per-day range vol, annualized) — needs ~80 recorded days to wake up."""
    if not _need_bars(ctx, 85):
        return None
    bars = ctx.bars
    assert bars is not None
    hl = np.log(bars.highs / bars.lows)
    daily_rv = np.sqrt((hl**2) / (4 * np.log(2)) * 252.0) * 100.0
    return est.har_rv_forecast(daily_rv)


def vov_20d(ctx: FeatureContext) -> float | None:
    if ctx.atm_iv_history is None or len(ctx.atm_iv_history) < 21:
        return None
    current = atm_iv(ctx.chain_front) if ctx.chain_front else None
    series = ctx.atm_iv_history if current is None else np.append(ctx.atm_iv_history, current)
    return est.vol_of_vol(series)


def iv_percentile_1y(ctx: FeatureContext) -> float | None:
    current = atm_iv(ctx.chain_front) if ctx.chain_front else None
    if current is None or ctx.atm_iv_history is None:
        return None
    return est.percentile_rank(ctx.atm_iv_history, current)


def iv_rank_1y(ctx: FeatureContext) -> float | None:
    current = atm_iv(ctx.chain_front) if ctx.chain_front else None
    if current is None or ctx.atm_iv_history is None:
        return None
    return est.iv_rank(ctx.atm_iv_history, current)


# ── term structure ───────────────────────────────────────────────────────────
def atm_iv_front(ctx: FeatureContext) -> float | None:
    return atm_iv(ctx.chain_front) if ctx.chain_front else None


def atm_iv_next(ctx: FeatureContext) -> float | None:
    return atm_iv(ctx.chain_next) if ctx.chain_next else None


def term_slope(ctx: FeatureContext) -> float | None:
    front, nxt = atm_iv_front(ctx), atm_iv_next(ctx)
    if front is None or nxt is None or front < 1.0:
        return None
    return (nxt - front) / front  # >0 contango, <0 inversion/stress


# ── skew ─────────────────────────────────────────────────────────────────────
def _skew(ctx: FeatureContext, key: str) -> float | None:
    if ctx.chain_front is None:
        return None
    return skew_metrics(ctx.chain_front)[key]


def put_skew_25d(ctx: FeatureContext) -> float | None:
    return _skew(ctx, "put_skew_25d")


def call_skew_25d(ctx: FeatureContext) -> float | None:
    return _skew(ctx, "call_skew_25d")


def smile_curvature(ctx: FeatureContext) -> float | None:
    return _skew(ctx, "smile_curvature")


# ── market ───────────────────────────────────────────────────────────────────
def gap_pct(ctx: FeatureContext) -> float | None:
    if not _need_bars(ctx, 2):
        return None
    bars = ctx.bars
    assert bars is not None
    return float((bars.opens[-1] / bars.closes[-2] - 1) * 100)


def overnight_ret(ctx: FeatureContext) -> float | None:
    return gap_pct(ctx)  # alias kept separate for downstream naming stability


def intraday_ret(ctx: FeatureContext) -> float | None:
    if not _need_bars(ctx, 1):
        return None
    bars = ctx.bars
    assert bars is not None
    return float((bars.closes[-1] / bars.opens[-1] - 1) * 100)


def atr_14(ctx: FeatureContext) -> float | None:
    if not _need_bars(ctx, 15):
        return None
    bars = ctx.bars
    assert bars is not None
    return est.atr(bars.highs, bars.lows, bars.closes)


def vix_percentile_1y(ctx: FeatureContext) -> float | None:
    if ctx.vix is None or ctx.vix.days < 21:
        return None
    return est.percentile_rank(ctx.vix.closes[:-1], float(ctx.vix.closes[-1]))


# ── flow ─────────────────────────────────────────────────────────────────────
def oi_total_front(ctx: FeatureContext) -> float | None:
    return total_oi(ctx.chain_front) if ctx.chain_front else None


def oi_change_1d(ctx: FeatureContext) -> float | None:
    current = oi_total_front(ctx)
    hist = ctx.oi_total_history
    if current is None or hist is None or len(hist) < 1 or hist[-1] <= 0:
        return None
    return float((current / hist[-1] - 1) * 100)


def oi_velocity_5d(ctx: FeatureContext) -> float | None:
    """Mean daily % change in total front OI over 5 days."""
    current = oi_total_front(ctx)
    hist = ctx.oi_total_history
    if current is None or hist is None or len(hist) < 5:
        return None
    series = np.append(hist[-5:], current)
    changes = np.diff(series) / series[:-1] * 100
    return float(np.mean(changes))


def oi_accel_5d(ctx: FeatureContext) -> float | None:
    """Change in OI velocity: today's 5d velocity minus the prior 5d window's."""
    current = oi_total_front(ctx)
    hist = ctx.oi_total_history
    if current is None or hist is None or len(hist) < 10:
        return None
    series = np.append(hist[-10:], current)
    changes = np.diff(series) / series[:-1] * 100
    return float(np.mean(changes[-5:]) - np.mean(changes[:-5]))


# ── participant (from NSE participant-wise OI; NIFTY-entity only — the file
#    is index-level, not per-underlying; stored under entity NSEIDX) ─────────
def _net_ratio(ctx: FeatureContext, participant: str, instrument_class: str) -> float | None:
    pair = ctx.participant.get((participant, instrument_class))
    if pair is None:
        return None
    longs, shorts = pair
    total = longs + shorts
    if total == 0:
        return None
    return float((longs - shorts) / total)  # -1..+1


def fii_net_idx_fut(ctx: FeatureContext) -> float | None:
    return _net_ratio(ctx, "FII", "IDX_FUT")


def dii_net_idx_fut(ctx: FeatureContext) -> float | None:
    return _net_ratio(ctx, "DII", "IDX_FUT")


def client_net_idx_fut(ctx: FeatureContext) -> float | None:
    return _net_ratio(ctx, "CLIENT", "IDX_FUT")


def client_net_idx_calls(ctx: FeatureContext) -> float | None:
    return _net_ratio(ctx, "CLIENT", "IDX_OPT_CALL")


def client_net_idx_puts(ctx: FeatureContext) -> float | None:
    return _net_ratio(ctx, "CLIENT", "IDX_OPT_PUT")


REGISTRY: list[FeatureSpec] = [
    FeatureSpec("rv_cc_20d", "1", "vol", rv_cc_20d, "20d close-close RV, ann %"),
    FeatureSpec("rv_pk_20d", "1", "vol", rv_pk_20d, "20d Parkinson RV, ann %"),
    FeatureSpec("rv_yz_20d", "1", "vol", rv_yz_20d, "20d Yang-Zhang RV, ann %"),
    FeatureSpec("har_rv_forecast_1d", "1", "vol", har_rv_forecast_1d, "HAR-RV t+1 forecast"),
    FeatureSpec("vov_20d", "1", "vol", vov_20d, "stdev of daily ATM IV changes, 20d"),
    FeatureSpec("iv_percentile_1y", "1", "vol", iv_percentile_1y, "ATM IV percentile vs 1y"),
    FeatureSpec("iv_rank_1y", "1", "vol", iv_rank_1y, "ATM IV rank vs 1y range"),
    FeatureSpec("atm_iv_front", "1", "term", atm_iv_front, "front-expiry ATM IV"),
    FeatureSpec("atm_iv_next", "1", "term", atm_iv_next, "next-expiry ATM IV"),
    FeatureSpec("term_slope", "1", "term", term_slope, "(next-front)/front"),
    FeatureSpec("put_skew_25d", "1", "skew", put_skew_25d, "25Δ put IV - ATM IV"),
    FeatureSpec("call_skew_25d", "1", "skew", call_skew_25d, "25Δ call IV - ATM IV"),
    FeatureSpec("smile_curvature", "1", "skew", smile_curvature, "wing avg - ATM"),
    FeatureSpec("gap_pct", "1", "market", gap_pct, "open vs prev close, %"),
    FeatureSpec("overnight_ret", "1", "market", overnight_ret, "overnight return, %"),
    FeatureSpec("intraday_ret", "1", "market", intraday_ret, "open-to-close return, %"),
    FeatureSpec("atr_14", "1", "market", atr_14, "ATR(14), index points"),
    FeatureSpec("vix_percentile_1y", "1", "market", vix_percentile_1y, "India VIX percentile"),
    FeatureSpec("oi_total_front", "1", "flow", oi_total_front, "total front-expiry OI"),
    FeatureSpec("oi_change_1d", "1", "flow", oi_change_1d, "1d % change in front OI"),
    FeatureSpec("oi_velocity_5d", "1", "flow", oi_velocity_5d, "mean 5d OI % change"),
    FeatureSpec("oi_accel_5d", "1", "flow", oi_accel_5d, "velocity change between 5d windows"),
    FeatureSpec("fii_net_idx_fut", "1", "participant", fii_net_idx_fut, "FII net idx fut ratio"),
    FeatureSpec("dii_net_idx_fut", "1", "participant", dii_net_idx_fut, "DII net idx fut ratio"),
    FeatureSpec("client_net_idx_fut", "1", "participant", client_net_idx_fut, "Client net idx fut"),
    FeatureSpec(
        "client_net_idx_calls", "1", "participant", client_net_idx_calls, "Client net calls"
    ),
    FeatureSpec("client_net_idx_puts", "1", "participant", client_net_idx_puts, "Client net puts"),
]
