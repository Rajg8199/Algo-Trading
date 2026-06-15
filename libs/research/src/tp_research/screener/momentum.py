"""Cross-sectional 12-1 momentum — a portfolio/ranking strategy (distinct from
the single-name breakout). Rank the universe by trailing-12m-skip-1m return,
hold the top decile equal-weight, rebalance monthly, go to cash when the broad
market is below its 200-DMA. Backtest reports portfolio metrics vs an
equal-weight benchmark. No edge is assumed — the gate decides.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from tp_research.screener.models import DailyBar


@dataclass(frozen=True)
class MomentumParams:
    lookback: int = 252  # ~12 months
    skip: int = 21  # ~1 month (12-1: skip the most recent month)
    top_pct: float = 0.1  # top decile
    min_names: int = 15
    max_names: int = 40
    rebalance_days: int = 21  # monthly
    cost_pct: float = 0.002  # charged on turned-over fraction per rebalance
    regime_sma: int = 200
    use_regime: bool = True

    @property
    def min_history(self) -> int:
        return self.lookback + self.skip + 1


@dataclass(frozen=True)
class PortfolioResult:
    n_rebalances: int
    ann_return_pct: float
    ann_vol_pct: float
    sharpe: float
    max_drawdown_pct: float
    hit_rate: float  # fraction of periods positive
    total_return_pct: float
    benchmark_ann_return_pct: float
    excess_ann_pct: float

    @property
    def acceptable(self) -> bool:
        """Frozen gate from docs/research/momentum-screen.md (H-MOM-01)."""
        return (
            self.n_rebalances >= 18
            and self.ann_return_pct > self.benchmark_ann_return_pct
            and self.sharpe > 0.8
            and self.max_drawdown_pct < 35.0
        )


def _market_level(closes: dict[str, dict[date, float]], axis: list[date]) -> list[float]:
    """Equal-weight daily-return index over the global date axis."""
    level = 1.0
    out: list[float] = []
    prev: date | None = None
    for d in axis:
        if prev is not None:
            rets = [
                dc[d] / dc[prev] - 1.0
                for dc in closes.values()
                if d in dc and prev in dc and dc[prev] > 0
            ]
            if rets:
                level *= 1.0 + sum(rets) / len(rets)
        out.append(level)
        prev = d
    return out


def _select(
    closes: dict[str, dict[date, float]], axis: list[date], i: int, params: MomentumParams
) -> list[str]:
    """Top-momentum names eligible at axis[i]."""
    d, d_skip, d_back = axis[i], axis[i - params.skip], axis[i - params.lookback]
    scored: list[tuple[float, str]] = []
    for sym, dc in closes.items():
        if d in dc and d_skip in dc and d_back in dc and dc[d_back] > 0:
            scored.append((dc[d_skip] / dc[d_back] - 1.0, sym))
    if not scored:
        return []
    scored.sort(reverse=True)
    n = max(params.min_names, min(params.max_names, round(params.top_pct * len(scored))))
    return [sym for _, sym in scored[:n]]


def _period_return(
    closes: dict[str, dict[date, float]], held: list[str], d0: date, d1: date
) -> float:
    rets = [
        closes[s][d1] / closes[s][d0] - 1.0
        for s in held
        if d0 in closes[s] and d1 in closes[s] and closes[s][d0] > 0
    ]
    return sum(rets) / len(rets) if rets else 0.0


def _eligible_all(closes: dict[str, dict[date, float]], d0: date, d1: date) -> list[str]:
    return [s for s, dc in closes.items() if d0 in dc and d1 in dc and dc[d0] > 0]


def backtest_momentum(
    bars_by_symbol: dict[str, Sequence[DailyBar]], params: MomentumParams
) -> PortfolioResult:
    closes = {sym: {b.day: b.close for b in hist} for sym, hist in bars_by_symbol.items()}
    axis = sorted({b.day for hist in bars_by_symbol.values() for b in hist})
    if len(axis) <= params.min_history:
        return PortfolioResult(0, 0, 0, 0, 0, 0, 0, 0, 0)

    market = _market_level(closes, axis)
    rebal = list(range(params.min_history, len(axis) - 1, params.rebalance_days))

    strat: list[float] = []
    bench: list[float] = []
    prev_held: set[str] = set()
    for k, i in enumerate(rebal):
        j = rebal[k + 1] if k + 1 < len(rebal) else len(axis) - 1
        d0, d1 = axis[i], axis[j]

        risk_on = True
        if params.use_regime and i >= params.regime_sma:
            risk_on = market[i] > sum(market[i + 1 - params.regime_sma : i + 1]) / params.regime_sma

        held = _select(closes, axis, i, params) if risk_on else []
        gross = _period_return(closes, held, d0, d1) if held else 0.0
        new_set = set(held)
        denom = len(new_set) + len(prev_held)
        turnover = len(new_set ^ prev_held) / denom if denom else 0.0
        strat.append(gross - params.cost_pct * turnover)
        prev_held = new_set

        bench.append(_period_return(closes, _eligible_all(closes, d0, d1), d0, d1))

    return _summarize_portfolio(strat, bench, params)


def _ann_stats(returns: Sequence[float], ppy: float) -> tuple[float, float, float, float, float]:
    """-> (ann_return_pct, ann_vol_pct, sharpe, max_dd_pct, total_return_pct)."""
    n = len(returns)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    total = equity - 1.0
    ann_return = equity ** (ppy / n) - 1.0 if equity > 0 else -1.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n
    std = math.sqrt(var)
    ann_vol = std * math.sqrt(ppy)
    sharpe = (mean * ppy) / ann_vol if ann_vol > 0 else 0.0
    return ann_return * 100, ann_vol * 100, sharpe, max_dd * 100, total * 100


def _summarize_portfolio(
    strat: Sequence[float], bench: Sequence[float], params: MomentumParams
) -> PortfolioResult:
    ppy = 252.0 / params.rebalance_days
    ann_r, ann_v, sharpe, max_dd, total = _ann_stats(strat, ppy)
    bench_ann, *_ = _ann_stats(bench, ppy)
    hits = sum(1 for r in strat if r > 0) / len(strat) if strat else 0.0
    return PortfolioResult(
        n_rebalances=len(strat),
        ann_return_pct=ann_r,
        ann_vol_pct=ann_v,
        sharpe=sharpe,
        max_drawdown_pct=max_dd,
        hit_rate=hits,
        total_return_pct=total,
        benchmark_ann_return_pct=bench_ann,
        excess_ann_pct=ann_r - bench_ann,
    )


def current_picks(
    bars_by_symbol: dict[str, Sequence[DailyBar]], params: MomentumParams
) -> tuple[list[str], bool]:
    """Today's momentum holdings and the current regime flag (risk_on)."""
    closes = {sym: {b.day: b.close for b in hist} for sym, hist in bars_by_symbol.items()}
    axis = sorted({b.day for hist in bars_by_symbol.values() for b in hist})
    if len(axis) <= params.min_history:
        return [], False
    i = len(axis) - 1
    risk_on = True
    if params.use_regime and i >= params.regime_sma:
        market = _market_level(closes, axis)
        risk_on = market[i] > sum(market[i + 1 - params.regime_sma : i + 1]) / params.regime_sma
    held = _select(closes, axis, i, params) if risk_on else []
    return held, risk_on
