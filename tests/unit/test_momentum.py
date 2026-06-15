"""Cross-sectional momentum tests. A synthetic universe where one cohort
strictly out-trends another lets us assert that the strategy actually selects
and rides the winners, and that the gate/metrics are well-formed."""

from __future__ import annotations

from datetime import date, timedelta

from tp_research.screener import DailyBar, MomentumParams, backtest_momentum, current_picks
from tp_research.screener.momentum import _ann_stats

START = date(2023, 1, 2)


def _bars(symbol: str, closes: list[float]) -> list[DailyBar]:
    out: list[DailyBar] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        day = START + timedelta(days=i)
        out.append(DailyBar(symbol, day, prev, max(prev, c), min(prev, c), c, 1_000_000))
        prev = c
    return out


def test_ann_stats_basic() -> None:
    # positive-drift returns with some variance -> positive annualized + Sharpe
    ann_r, _ann_v, sharpe, max_dd, _total = _ann_stats([0.02, 0.0, 0.03, 0.01, 0.02, 0.0] * 3, 12.0)
    assert ann_r > 0
    assert sharpe > 0
    assert max_dd >= 0.0


def test_momentum_prefers_strong_cohort() -> None:
    n = 360
    universe = {}
    # 20 strong names trending up, 20 weak names trending down
    for k in range(20):
        universe[f"UP{k}"] = _bars(f"UP{k}", [100.0 + i * (0.5 + k * 0.01) for i in range(n)])
    for k in range(20):
        universe[f"DN{k}"] = _bars(f"DN{k}", [300.0 - i * (0.5 + k * 0.01) for i in range(n)])

    params = MomentumParams(min_names=5, max_names=10, use_regime=False)
    held, _ = current_picks(universe, params)
    assert held, "expected some holdings"
    # every pick should come from the up-trending cohort
    assert all(s.startswith("UP") for s in held)


def test_momentum_backtest_beats_benchmark_on_constructed_edge() -> None:
    n = 400
    universe = {}
    for k in range(15):
        universe[f"UP{k}"] = _bars(f"UP{k}", [100.0 + i * (0.6 + k * 0.02) for i in range(n)])
    for k in range(15):
        # choppy / flat names — weak momentum
        universe[f"FL{k}"] = _bars(f"FL{k}", [100.0 + (i % 10) * 0.2 for i in range(n)])

    params = MomentumParams(min_names=5, max_names=8, use_regime=False)
    res = backtest_momentum(universe, params)
    assert res.n_rebalances > 0
    # picking the strongest trends should beat the equal-weight benchmark here
    assert res.ann_return_pct > res.benchmark_ann_return_pct


def test_regime_off_market_goes_to_cash() -> None:
    # whole universe declining -> market below its 200-DMA -> hold cash (no picks)
    n = 360
    universe = {f"DN{k}": _bars(f"DN{k}", [300.0 - i * 0.5 for i in range(n)]) for k in range(20)}
    held, risk_on = current_picks(universe, MomentumParams(use_regime=True))
    assert not risk_on
    assert held == []
