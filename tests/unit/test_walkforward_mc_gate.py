from datetime import date

import numpy as np
from tp_backtest.fills import FillScenario
from tp_backtest.metrics import Metrics
from tp_backtest.montecarlo import monte_carlo
from tp_backtest.validation import evaluate
from tp_backtest.walkforward import assert_no_overlap, walk_forward_windows

RNG = np.random.default_rng(7)


# ── walk-forward ─────────────────────────────────────────────────────────────
def test_windows_no_leakage_rolling_and_anchored() -> None:
    for anchored in (False, True):
        windows = list(
            walk_forward_windows(
                date(2024, 1, 1),
                date(2025, 12, 31),
                train_days=180,
                validate_days=60,
                purge_days=7,
                anchored=anchored,
            )
        )
        assert len(windows) >= 5
        assert_no_overlap(windows)
        for w in windows:
            # purge respected and validation starts the day after a Tuesday expiry
            assert (w.validate_start - w.train_end).days >= 7
            assert w.validate_start.weekday() == 2  # Wednesday


def test_anchored_keeps_train_start_fixed() -> None:
    windows = list(
        walk_forward_windows(date(2024, 1, 1), date(2025, 6, 30), 180, 60, anchored=True)
    )
    assert all(w.train_start == date(2024, 1, 1) for w in windows)


# ── monte carlo ──────────────────────────────────────────────────────────────
def make_pnls(n: int = 200) -> list[float]:
    return list(RNG.normal(500, 3000, n))


def test_mc_deterministic_with_seed() -> None:
    pnls = make_pnls()
    a = monte_carlo(pnls, seed=42)
    b = monte_carlo(pnls, seed=42)
    assert a is not None and b is not None
    assert a.max_dd_p95 == b.max_dd_p95
    assert a.risk_of_ruin == b.risk_of_ruin


def test_mc_percentiles_ordered() -> None:
    report = monte_carlo(make_pnls(), seed=1)
    assert report is not None
    assert report.max_dd_p95 <= report.max_dd_p99 <= report.max_dd_p999
    assert report.pnl_lower_p95 >= report.pnl_lower_p99 >= report.pnl_lower_p999


def test_mc_refuses_tiny_samples() -> None:
    assert monte_carlo([100.0] * 10) is None


def test_mc_block_vs_iid_both_run() -> None:
    pnls = make_pnls()
    assert monte_carlo(pnls, method="iid") is not None
    assert monte_carlo(pnls, method="block") is not None


# ── acceptance gate ──────────────────────────────────────────────────────────
def good_metrics() -> Metrics:
    return Metrics(
        net_pnl=400_000,
        sharpe=2.1,
        profit_factor=1.9,
        expectancy=1500.0,
        max_drawdown=60_000,
        max_drawdown_pct=6.0,
        win_rate=0.6,
        n_trades=250,
        n_days=300,
        total_costs=80_000,
        unfillable_orders=2,
    )


def test_gate_accepts_strong_strategy() -> None:
    mc = monte_carlo(make_pnls(250), seed=3)
    verdict = evaluate(
        expected_metrics=good_metrics(),
        capital=1_000_000,
        mc=mc,
        walkforward_oos_metrics=good_metrics(),
        regime_sharpes={"low": 1.2, "mid": 2.0, "high": 0.8},
    )
    assert verdict.accepted, verdict.summary()


def test_gate_rejects_on_any_single_failure() -> None:
    weak = good_metrics().__dict__ | {"sharpe": 1.2}
    verdict = evaluate(
        expected_metrics=Metrics(**weak),
        capital=1_000_000,
        mc=monte_carlo(make_pnls(250), seed=3),
        walkforward_oos_metrics=good_metrics(),
        regime_sharpes={"low": 1.2, "mid": 2.0, "high": 0.8},
    )
    assert not verdict.accepted
    assert any(g.name == "sharpe" for g in verdict.failures)


def test_gate_rejects_missing_evidence() -> None:
    verdict = evaluate(
        expected_metrics=good_metrics(),
        capital=1_000_000,
        mc=None,  # no Monte Carlo
        walkforward_oos_metrics=None,  # no walk-forward
        regime_sharpes=None,  # no regime analysis
    )
    assert not verdict.accepted
    failed = {g.name for g in verdict.failures}
    assert {"monte_carlo", "walk_forward", "regime_analysis"} <= failed


def test_gate_rejects_negative_regime() -> None:
    verdict = evaluate(
        expected_metrics=good_metrics(),
        capital=1_000_000,
        mc=monte_carlo(make_pnls(250), seed=3),
        walkforward_oos_metrics=good_metrics(),
        regime_sharpes={"low": 1.2, "mid": 2.0, "high": -0.4},
    )
    assert not verdict.accepted
    assert any(g.name == "regime_analysis" for g in verdict.failures)


def test_gate_rejects_best_case_judgment() -> None:
    verdict = evaluate(
        expected_metrics=good_metrics(),
        capital=1_000_000,
        mc=monte_carlo(make_pnls(250), seed=3),
        walkforward_oos_metrics=good_metrics(),
        regime_sharpes={"mid": 2.0},
        scenario=FillScenario.BEST,
    )
    assert not verdict.accepted
