"""Experiment 001 orchestration: the full 4D sequence as one auditable run.

Sequence (fixed): preflight -> in-sample grid -> walk-forward -> Monte Carlo
-> regime testing -> cost stress -> decision. The decision framework
evaluates REJECT conditions FIRST — the run exists to disprove the strategy.
"""

import itertools
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

import numpy as np

from tp_backtest.engine import BacktestConfig, BacktestResult, run_backtest
from tp_backtest.fills import FillScenario
from tp_backtest.metrics import (
    Metrics,
    compute_metrics,
    deflated_sharpe,
    metrics_from_series,
    trade_pnls,
)
from tp_backtest.montecarlo import MonteCarloReport, monte_carlo
from tp_backtest.strategies.vrp import ConditionalVRP, VRPParams
from tp_backtest.validation import Verdict, evaluate
from tp_backtest.walkforward import Window, walk_forward_windows
from tp_core.strategy import MarketState

# ── 4C: the registered grid. 72 combinations. Frozen. ───────────────────────
REGISTERED_GRID: dict[str, list[object]] = {
    "min_vrp_points": [1.0, 2.0, 3.0],
    "min_iv_percentile": [70.0, 80.0, 90.0],
    "max_vov": [1.0, 1.5],
    "event_exclusion": [True, False],
    "stop_mult": [1.5, 2.0],
}

MIN_PREFLIGHT_DAYS = 120
# Weekly cadence yields ~26 entries per 180d train window; 30 would be
# unreachable by construction. 15 = registered floor (vrp-experiment-001).
MIN_TRAIN_TRADES = 15


def grid_combos(event_days: frozenset[date], base: VRPParams | None = None) -> list[VRPParams]:
    base = base or VRPParams()
    combos = []
    keys = list(REGISTERED_GRID)
    for values in itertools.product(*(REGISTERED_GRID[k] for k in keys)):
        kv = dict(zip(keys, values, strict=True))
        exclusion = kv.pop("event_exclusion")
        combos.append(
            replace(
                base,
                **kv,  # type: ignore[arg-type]
                excluded_entry_days=event_days if exclusion else frozenset(),
            )
        )
    return combos


class Decision(StrEnum):
    REJECT = "REJECT"
    INVESTIGATE = "INVESTIGATE"
    PROMISING = "PROMISING"
    ADVANCE = "ADVANCE_TO_PAPER_TRADING"


@dataclass
class WalkForwardOutcome:
    windows: list[Window]
    selections: list[VRPParams]
    oos_daily: list[float]
    oos_trades: list[float]
    oos_total_costs: float
    oos_unfillable: int
    negative_window_ratio: float
    oos_daily_by_date: dict[date, float] = field(default_factory=dict)


@dataclass
class ExperimentReport:
    decision: Decision
    reasons: list[str]
    verdict: Verdict | None
    oos_metrics: dict[FillScenario, Metrics]
    mc: MonteCarloReport | None
    regime_sharpes: dict[str, float]
    dsr: float | None
    n_trials: int
    in_sample_surface: list[tuple[dict[str, object], float | None]]

    def summary(self) -> str:
        lines = [f"DECISION: {self.decision.value}"]
        lines += [f"  - {r}" for r in self.reasons]
        if self.verdict:
            lines.append(self.verdict.summary())
        return "\n".join(lines)


def _slice(
    states_by_day: dict[date, list[MarketState]], start: date, end: date
) -> list[MarketState]:
    out: list[MarketState] = []
    for day in sorted(states_by_day):
        if start <= day <= end:
            out.extend(states_by_day[day])
    return out


def _run(
    params: VRPParams,
    states: list[MarketState],
    scenario: FillScenario,
    capital: float,
    dataset_version: str,
    synthetic_spread_pct: float | None = None,
) -> tuple[BacktestResult, Metrics]:
    config = BacktestConfig(
        scenario=scenario,
        capital=Decimal(str(capital)),
        dataset_version=dataset_version,
        synthetic_spread_pct=synthetic_spread_pct,
    )
    result = run_backtest(ConditionalVRP(params), states, config)
    return result, compute_metrics(result)


def in_sample_grid(
    states_by_day: dict[date, list[MarketState]],
    combos: list[VRPParams],
    capital: float,
    dataset_version: str,
    synthetic_spread_pct: float | None = None,
) -> list[tuple[dict[str, object], float | None]]:
    """Full-range grid under EXPECTED fills. Output: parameter surface for
    sanity inspection (cliff-edge maxima => suspect) and trial accounting."""
    days = sorted(states_by_day)
    if not days:
        return []
    states = _slice(states_by_day, days[0], days[-1])
    surface = []
    for params in combos:
        _, metrics = _run(
            params, states, FillScenario.EXPECTED, capital, dataset_version, synthetic_spread_pct
        )
        surface.append((_params_key(params), metrics.sharpe))
    return surface


def _params_key(p: VRPParams) -> dict[str, object]:
    return {
        "min_vrp_points": p.min_vrp_points,
        "min_iv_percentile": p.min_iv_percentile,
        "max_vov": p.max_vov,
        "event_exclusion": bool(p.excluded_entry_days),
        "stop_mult": p.stop_mult,
    }


def walk_forward_run(
    states_by_day: dict[date, list[MarketState]],
    combos: list[VRPParams],
    capital: float,
    dataset_version: str,
    scenario: FillScenario = FillScenario.EXPECTED,
    train_days: int = 180,
    validate_days: int = 60,
    synthetic_spread_pct: float | None = None,
) -> WalkForwardOutcome | None:
    days = sorted(states_by_day)
    if not days:
        return None
    windows = list(walk_forward_windows(days[0], days[-1], train_days, validate_days, purge_days=7))
    if not windows:
        return None

    selections: list[VRPParams] = []
    oos_daily: list[float] = []
    oos_daily_by_date: dict[date, float] = {}
    oos_trades: list[float] = []
    total_costs = 0.0
    unfillable = 0
    negative_windows = 0

    for window in windows:
        train_states = _slice(states_by_day, window.train_start, window.train_end)
        # Selection rule (registered): max train net Sharpe, >=30 train
        # trades; tie -> lower stop_mult (more conservative).
        best: tuple[float, float, VRPParams] | None = None
        for params in combos:
            _, m = _run(
                params, train_states, scenario, capital, dataset_version, synthetic_spread_pct
            )
            if m.n_trades < MIN_TRAIN_TRADES or m.sharpe is None:
                continue
            key = (m.sharpe, -params.stop_mult)
            if best is None or key > (best[0], best[1]):
                best = (m.sharpe, -params.stop_mult, params)
        if best is None:
            continue  # no qualifying combo in this window: contributes nothing
        selected = best[2]
        selections.append(selected)

        validate_states = _slice(states_by_day, window.validate_start, window.validate_end)
        result, _ = _run(
            selected, validate_states, scenario, capital, dataset_version, synthetic_spread_pct
        )
        window_pnl = float(result.final_pnl)
        if window_pnl < 0:
            negative_windows += 1
        for day, pnl in result.daily_pnl.items():
            oos_daily.append(float(pnl))
            oos_daily_by_date[day] = float(pnl)
        oos_trades.extend(trade_pnls(result))
        total_costs += float(result.total_costs)
        unfillable += result.unfillable_orders

    if not selections:
        return None
    return WalkForwardOutcome(
        windows=windows,
        selections=selections,
        oos_daily=oos_daily,
        oos_trades=oos_trades,
        oos_total_costs=total_costs,
        oos_unfillable=unfillable,
        negative_window_ratio=negative_windows / len(selections),
        oos_daily_by_date=oos_daily_by_date,
    )


def cost_stress(
    states_by_day: dict[date, list[MarketState]],
    outcome: WalkForwardOutcome,
    capital: float,
    dataset_version: str,
    synthetic_spread_pct: float | None = None,
) -> dict[FillScenario, Metrics]:
    """Re-run each window's SELECTED combo on its validation segment under
    BEST and WORST; EXPECTED comes from the walk-forward itself."""
    out: dict[FillScenario, Metrics] = {
        FillScenario.EXPECTED: metrics_from_series(
            outcome.oos_daily,
            outcome.oos_trades,
            capital,
            outcome.oos_total_costs,
            outcome.oos_unfillable,
        )
    }
    for scenario in (FillScenario.BEST, FillScenario.WORST):
        daily: list[float] = []
        trades: list[float] = []
        costs = 0.0
        unfillable = 0
        for window, selected in zip(outcome.windows, outcome.selections, strict=False):
            states = _slice(states_by_day, window.validate_start, window.validate_end)
            result, _ = _run(
                selected, states, scenario, capital, dataset_version, synthetic_spread_pct
            )
            daily.extend(float(p) for p in result.daily_pnl.values())
            trades.extend(trade_pnls(result))
            costs += float(result.total_costs)
            unfillable += result.unfillable_orders
        out[scenario] = metrics_from_series(daily, trades, capital, costs, unfillable)
    return out


def regime_split(
    oos_daily_by_date: dict[date, float],
    vix_percentile_by_day: dict[date, float],
    capital: float,
) -> dict[str, float]:
    import math

    buckets: dict[str, list[float]] = {"low": [], "mid": [], "high": []}
    for day, pnl in oos_daily_by_date.items():
        pct = vix_percentile_by_day.get(day)
        if pct is None:
            continue
        bucket = "low" if pct < 30 else ("mid" if pct <= 70 else "high")
        buckets[bucket].append(pnl)
    out: dict[str, float] = {}
    for name, pnls in buckets.items():
        if len(pnls) < 15:
            continue
        arr = np.asarray(pnls) / capital
        std = float(np.std(arr, ddof=1))
        if std > 1e-12:
            out[name] = float(np.mean(arr) / std * math.sqrt(252))
    return out


def decide(
    oos: dict[FillScenario, Metrics],
    mc: MonteCarloReport | None,
    regimes: dict[str, float],
    dsr: float | None,
    verdict: Verdict,
    negative_window_ratio: float,
) -> tuple[Decision, list[str]]:
    """4F decision framework. REJECT conditions evaluated FIRST."""
    m = oos[FillScenario.EXPECTED]
    reasons: list[str] = []

    # ── REJECT (terminal) ────────────────────────────────────────────────
    if m.expectancy is not None and m.expectancy <= 0:
        reasons.append(f"OOS expectancy <= 0 ({m.expectancy:.0f})")
    if mc is not None and mc.risk_of_ruin > 0.01:
        reasons.append(f"MC ruin {mc.risk_of_ruin:.2%} > 1%")
    negative_regimes = [k for k, v in regimes.items() if v < 0]
    if len(negative_regimes) >= 2:
        reasons.append(f"negative in regimes: {negative_regimes}")
    total_orders = m.n_trades + m.unfillable_orders
    if total_orders and m.unfillable_orders / total_orders > 0.05:
        reasons.append("unfillable > 5%")
    if negative_window_ratio >= 0.40:
        reasons.append(f"{negative_window_ratio:.0%} of WF windows negative")
    if reasons:
        return Decision.REJECT, reasons

    # ── ADVANCE ──────────────────────────────────────────────────────────
    worst = oos[FillScenario.WORST]
    if (
        verdict.accepted
        and dsr is not None
        and dsr >= 0.90
        and worst.expectancy is not None
        and worst.expectancy > 0
    ):
        return Decision.ADVANCE, ["all gates passed", f"DSR={dsr:.3f}", "worst-case expectancy > 0"]

    # ── PROMISING ────────────────────────────────────────────────────────
    if (
        m.sharpe is not None
        and m.sharpe >= 1.0
        and m.expectancy is not None
        and m.expectancy > 0
        and m.max_drawdown_pct <= 12.0
        and m.n_trades >= 60
        and all(v >= -0.5 for v in regimes.values())
    ):
        failed = [g.name for g in verdict.failures]
        return Decision.PROMISING, [
            f"near-miss; failed gates: {failed}",
            "action: extend data, re-run SAME grid",
        ]

    # ── INVESTIGATE (default for anything not dead and not good) ────────
    return Decision.INVESTIGATE, [
        f"sharpe={m.sharpe}, expectancy={m.expectancy}, trades={m.n_trades}",
        "action: diagnose; no promotion, no tuning",
    ]


def run_experiment_001(
    states_by_day: dict[date, list[MarketState]],
    event_days: frozenset[date],
    vix_percentile_by_day: dict[date, float],
    capital: float,
    dataset_version: str,
    prior_trials: int = 0,
    base_params: VRPParams | None = None,
    synthetic_spread_pct: float | None = None,
) -> ExperimentReport:
    """`base_params` seeds the registered grid (e.g. the EXP-001-EOD widened
    decision window); `synthetic_spread_pct` enables fills on quote-less data
    (bhavcopy). Both default to None = the intraday Experiment 001 exactly."""
    combos = grid_combos(event_days, base=base_params)
    n_trials = prior_trials + len(combos)

    surface = in_sample_grid(states_by_day, combos, capital, dataset_version, synthetic_spread_pct)
    wf = walk_forward_run(
        states_by_day, combos, capital, dataset_version, synthetic_spread_pct=synthetic_spread_pct
    )
    if wf is None:
        return ExperimentReport(
            decision=Decision.INVESTIGATE,
            reasons=["walk-forward produced no qualifying windows (insufficient data/trades)"],
            verdict=None,
            oos_metrics={},
            mc=None,
            regime_sharpes={},
            dsr=None,
            n_trials=n_trials,
            in_sample_surface=surface,
        )

    oos = cost_stress(states_by_day, wf, capital, dataset_version, synthetic_spread_pct)
    mc = monte_carlo(wf.oos_trades, method="block", seed=42, ruin_level=150_000.0)
    regimes = regime_split(wf.oos_daily_by_date, vix_percentile_by_day, capital)

    expected = oos[FillScenario.EXPECTED]
    dsr = None
    if expected.sharpe is not None:
        dsr = deflated_sharpe(
            expected.sharpe,
            expected.n_days,
            n_trials,
            np.asarray(wf.oos_daily) / capital if wf.oos_daily else None,
        )

    verdict = evaluate(
        expected_metrics=expected,
        capital=capital,
        mc=mc,
        walkforward_oos_metrics=expected,
        regime_sharpes=regimes,
    )
    decision, reasons = decide(oos, mc, regimes, dsr, verdict, wf.negative_window_ratio)
    return ExperimentReport(
        decision=decision,
        reasons=reasons,
        verdict=verdict,
        oos_metrics=oos,
        mc=mc,
        regime_sharpes=regimes,
        dsr=dsr,
        n_trials=n_trials,
        in_sample_surface=surface,
    )
