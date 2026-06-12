"""Signal payloads for Telegram. Every field the lab promises, every signal.

Confidence is a TRANSPARENT HEURISTIC, not a probability: the minimum
normalized margin by which the entry filters cleared their thresholds,
squashed to 0-100. Documented so nobody mistakes it for a calibrated number.
"""

from dataclasses import dataclass

from tp_backtest.strategies.vrp import VRPParams

from tp_core.strategy import MarketState


@dataclass(frozen=True)
class SignalCard:
    index: str
    direction: str
    strikes: str
    entry: str
    stop_loss: str
    target: str
    timeframe: str
    confidence: int
    strategy: str
    reason: str

    def telegram_text(self) -> str:
        return (
            f"📡 PAPER SIGNAL — {self.strategy} (UNVALIDATED · forward-test)\n"
            f"Index: {self.index}\n"
            f"Direction: {self.direction}\n"
            f"Strikes: {self.strikes}\n"
            f"Entry: {self.entry}\n"
            f"Stop Loss: {self.stop_loss}\n"
            f"Target: {self.target}\n"
            f"Timeframe: {self.timeframe}\n"
            f"Confidence: {self.confidence}/100 (filter-margin heuristic)\n"
            f"Reason: {self.reason}"
        )


def confidence_score(state: MarketState, params: VRPParams) -> int:
    """Min normalized filter margin -> 0..100. 50 = filters just barely passed."""
    f = state.features.get(params.underlying, {})
    iv = f.get("atm_iv_front")
    rv = f.get("har_rv_forecast_1d")
    iv_pct = f.get("iv_percentile_1y")
    vov = f.get("vov_20d")
    if iv is None or rv is None or iv_pct is None or vov is None:
        return 0
    margins = [
        (iv - rv - params.min_vrp_points) / max(params.min_vrp_points, 0.5),
        (iv_pct - params.min_iv_percentile) / max(100 - params.min_iv_percentile, 1.0),
        (params.max_vov - vov) / max(params.max_vov, 0.1),
    ]
    worst = max(min(margins), 0.0)
    return min(100, int(50 + 50 * min(worst, 1.0)))


def build_vrp_signal(
    state: MarketState,
    params: VRPParams,
    legs: list[tuple[str, float, str]],  # (side, strike, option_type)
    credit: float,
    expiry: str,
) -> SignalCard:
    f = state.features.get(params.underlying, {})
    iv = f.get("atm_iv_front")
    rv = f.get("har_rv_forecast_1d")
    vrp = (iv - rv) if (iv is not None and rv is not None) else None
    shorts = [leg for leg in legs if leg[0] == "SELL"]
    wings = [leg for leg in legs if leg[0] == "BUY"]
    return SignalCard(
        index=params.underlying,
        direction="SHORT PREMIUM (iron condor)",
        strikes=(
            "sell "
            + "/".join(f"{s:g}{t}" for _, s, t in shorts)
            + " · buy "
            + "/".join(f"{s:g}{t}" for _, s, t in wings)
        ),
        entry=f"net credit ≈ ₹{credit:,.0f}",
        stop_loss=(
            f"structure loss >= {params.stop_mult:g}x credit (₹{credit * params.stop_mult:,.0f})"
        ),
        target=f"hold to expiry {expiry}; capture credit",
        timeframe=f"{params.dte_min}-{params.dte_max} DTE weekly",
        confidence=confidence_score(state, params),
        strategy="vrp_nifty",
        reason=(
            f"VRP {vrp:.1f} vol pts (IV {iv:.1f} vs HAR-RV {rv:.1f}), "
            f"IV pct {f.get('iv_percentile_1y', float('nan')):.0f}, "
            f"vov {f.get('vov_20d', float('nan')):.2f} ≤ {params.max_vov:g}, "
            f"term slope {f.get('term_slope', float('nan')):.3f} ≥ 0"
            if vrp is not None
            else "filters passed (see features)"
        ),
    )
