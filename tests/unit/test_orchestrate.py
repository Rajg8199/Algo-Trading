"""Phase 4 orchestration tests: a synthetic VRP-friendly market (pinned spot,
decaying premiums, weekly Tuesday expiries) drives the full experiment
pipeline; the decision framework is tested path by path."""

from datetime import date, datetime, time, timedelta

import numpy as np
from tp_backtest.fills import FillScenario
from tp_backtest.metrics import Metrics, deflated_sharpe
from tp_backtest.montecarlo import monte_carlo
from tp_backtest.orchestrate import (
    Decision,
    decide,
    grid_combos,
    run_experiment_001,
    walk_forward_run,
)
from tp_backtest.strategies.vrp import VRPParams
from tp_backtest.validation import Verdict, evaluate

from tp_core.strategy import InstrumentMeta, MarketState, Quote
from tp_core.timeutils import IST

SPOT = 24500.0
LOT = 75

GOOD_FEATURES = {
    "NIFTY": {
        "atm_iv_front": 16.0,
        "har_rv_forecast_1d": 12.0,
        "iv_percentile_1y": 85.0,
        "vov_20d": 0.8,
        "term_slope": 0.05,
    }
}


def next_tuesday(d: date) -> date:
    return d + timedelta(days=(1 - d.weekday()) % 7 or 7)


def make_world(start: date, end: date) -> dict[date, list[MarketState]]:
    """Each weekly expiry gets 4 instruments: short CE/PE (~0.25d) and wing
    CE/PE (~0.10d). Premiums decay toward expiry; spot pinned -> condor wins."""
    states_by_day: dict[date, list[MarketState]] = {}
    iid = 0
    d = start
    instruments: dict[date, dict[str, int]] = {}
    meta: dict[int, InstrumentMeta] = {}

    expiry = next_tuesday(start)
    while expiry <= end + timedelta(days=7):
        legs = {}
        for name, opt, strike, _delta in (
            ("sc", "CE", SPOT + 200, 0.25),
            ("sp", "PE", SPOT - 200, -0.25),
            ("wc", "CE", SPOT + 400, 0.10),
            ("wp", "PE", SPOT - 400, -0.10),
        ):
            iid += 1
            legs[name] = iid
            meta[iid] = InstrumentMeta(iid, "NIFTY", "OPT", expiry, strike, opt, LOT)
        instruments[expiry] = legs
        expiry = next_tuesday(expiry)

    while d <= end:
        if d.weekday() < 5:
            active = [e for e in instruments if 0 <= (e - d).days <= 7]
            quotes: dict[int, Quote] = {}
            for e in active:
                dte = max((e - d).days, 0)
                decay = dte / 5.0
                for name, delta, base in (
                    ("sc", 0.25, 60.0),
                    ("sp", -0.25, 60.0),
                    ("wc", 0.10, 25.0),
                    ("wp", -0.10, 25.0),
                ):
                    px = max(base * decay, 0.5)
                    quotes[instruments[e][name]] = Quote(
                        instruments[e][name], px, px - 0.4, px + 0.4, iv=16.0, delta=delta
                    )
            day_states = []
            for minute in (19, 20, 21):
                ts = datetime.combine(d, time(15, minute), tzinfo=IST)
                day_states.append(
                    MarketState(
                        ts=ts,
                        spot={"NIFTY": SPOT},
                        quotes=dict(quotes),
                        meta=meta,
                        features=GOOD_FEATURES,
                    )
                )
            states_by_day[d] = day_states
        d += timedelta(days=1)
    return states_by_day


def small_combos() -> list[VRPParams]:
    return [
        VRPParams(min_vrp_points=1.0, min_iv_percentile=70.0, max_vov=1.5, stop_mult=2.0),
        VRPParams(min_vrp_points=2.0, min_iv_percentile=80.0, max_vov=1.5, stop_mult=1.5),
    ]


def test_grid_is_exactly_72_registered_combos() -> None:
    combos = grid_combos(frozenset({date(2026, 6, 5)}))
    assert len(combos) == 72
    assert (
        len(
            {
                str(
                    sorted(
                        (
                            p.min_vrp_points,
                            p.min_iv_percentile,
                            p.max_vov,
                            p.stop_mult,
                            bool(p.excluded_entry_days),
                        )
                        for p in [c]
                    )
                )
                for c in combos
            }
        )
        == 72
    )  # all distinct


def test_walk_forward_produces_oos_results() -> None:
    world = make_world(date(2025, 1, 1), date(2025, 12, 31))
    outcome = walk_forward_run(
        world, small_combos(), 1_000_000.0, "synthetic", train_days=120, validate_days=45
    )
    assert outcome is not None
    assert len(outcome.selections) >= 2
    assert len(outcome.oos_trades) > 10
    # Pinned market + short premium: OOS must be profitable here
    assert sum(outcome.oos_daily) > 0
    assert outcome.negative_window_ratio < 0.5


def test_full_experiment_synthetic(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import tp_backtest.orchestrate as orch

    monkeypatch.setattr(
        orch,
        "REGISTERED_GRID",
        {
            "min_vrp_points": [1.0],
            "min_iv_percentile": [70.0],
            "max_vov": [1.5],
            "event_exclusion": [False],
            "stop_mult": [2.0],
        },
    )
    world = make_world(date(2025, 1, 1), date(2026, 3, 31))
    report = run_experiment_001(
        states_by_day=world,
        event_days=frozenset(),
        vix_percentile_by_day=dict.fromkeys(world, 50.0),
        capital=1_000_000.0,
        dataset_version="synthetic",
        prior_trials=0,
    )
    assert report.decision in set(Decision)
    assert report.n_trials == 1
    assert report.in_sample_surface
    # Profitable synthetic world must not be REJECTED
    assert report.decision is not Decision.REJECT, report.summary()


# ── decision framework paths ─────────────────────────────────────────────────
def metrics_with(**overrides: object) -> Metrics:
    base = {
        "net_pnl": 300_000.0,
        "sharpe": 2.0,
        "profit_factor": 1.8,
        "expectancy": 1200.0,
        "max_drawdown": 50_000.0,
        "max_drawdown_pct": 5.0,
        "win_rate": 0.6,
        "n_trades": 150,
        "n_days": 250,
        "total_costs": 50_000.0,
        "unfillable_orders": 1,
    }
    base.update(overrides)
    return Metrics(**base)  # type: ignore[arg-type]


def make_verdict(metrics: Metrics) -> Verdict:
    mc = monte_carlo(list(np.random.default_rng(5).normal(800, 2500, 150)), seed=5)
    return evaluate(metrics, 1_000_000.0, mc, metrics, {"low": 1.0, "mid": 1.5, "high": 0.5})


def oos_pack(expected: Metrics, worst: Metrics | None = None) -> dict[FillScenario, Metrics]:
    return {
        FillScenario.BEST: expected,
        FillScenario.EXPECTED: expected,
        FillScenario.WORST: worst or expected,
    }


def test_decide_reject_on_negative_expectancy() -> None:
    m = metrics_with(expectancy=-50.0)
    decision, reasons = decide(oos_pack(m), None, {"mid": 1.0}, 0.95, make_verdict(m), 0.1)
    assert decision is Decision.REJECT
    assert any("expectancy" in r for r in reasons)


def test_decide_reject_on_unstable_windows() -> None:
    m = metrics_with()
    decision, _ = decide(oos_pack(m), None, {"mid": 1.0}, 0.95, make_verdict(m), 0.45)
    assert decision is Decision.REJECT


def test_decide_advance_requires_everything() -> None:
    m = metrics_with()
    mc = monte_carlo(list(np.random.default_rng(5).normal(800, 2500, 150)), seed=5)
    verdict = make_verdict(m)
    if verdict.accepted:
        decision, _ = decide(
            oos_pack(m), mc, {"low": 1.0, "mid": 1.5, "high": 0.5}, 0.95, verdict, 0.1
        )
        assert decision is Decision.ADVANCE
    # Same inputs but weak DSR -> not ADVANCE
    decision, _ = decide(oos_pack(m), mc, {"low": 1.0, "mid": 1.5, "high": 0.5}, 0.50, verdict, 0.1)
    assert decision is not Decision.ADVANCE


def test_decide_promising_near_miss() -> None:
    m = metrics_with(sharpe=1.2, n_trades=80)  # below 1.5 gate, decent
    verdict = evaluate(m, 1_000_000.0, None, None, {"mid": 1.0})  # gate fails (no MC/WF)
    decision, _ = decide(oos_pack(m), None, {"mid": 1.0}, 0.6, verdict, 0.1)
    assert decision is Decision.PROMISING


def test_decide_investigate_default() -> None:
    m = metrics_with(sharpe=0.4, n_trades=25, expectancy=100.0)
    verdict = evaluate(m, 1_000_000.0, None, None, {})
    decision, _ = decide(oos_pack(m), None, {}, None, verdict, 0.2)
    assert decision is Decision.INVESTIGATE


# ── deflated sharpe ──────────────────────────────────────────────────────────
def test_dsr_decreases_with_trials() -> None:
    values = [deflated_sharpe(2.0, 250, n) for n in (1, 10, 72, 500)]
    assert all(v is not None for v in values)
    assert values == sorted(values, reverse=True)  # type: ignore[type-var]


def test_dsr_small_sample_is_none() -> None:
    assert deflated_sharpe(2.0, 10, 72) is None
