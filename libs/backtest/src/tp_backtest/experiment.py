"""Experiment orchestrator: one call = one registered, reproducible,
fully-judged experiment.

Pipeline: fingerprint dataset → replay under all three fill scenarios →
metrics per scenario → Monte Carlo + regime stratification on EXPECTED →
acceptance gate → artifacts to datalake → row in `experiments` (trial counter
assigned by the registry, not the caller).
"""

import csv
import json
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from tp_backtest.engine import BacktestConfig, BacktestResult, run_backtest
from tp_backtest.fills import FillScenario
from tp_backtest.metrics import Metrics, compute_metrics, trade_pnls
from tp_backtest.montecarlo import MonteCarloReport, monte_carlo
from tp_backtest.validation import Verdict, evaluate
from tp_core.db import Database
from tp_core.db.repos import ExperimentRepo
from tp_core.strategy import MarketState, Strategy


@dataclass
class ExperimentOutcome:
    run_id: str
    trial_number: int
    verdict: Verdict
    metrics_by_scenario: dict[FillScenario, Metrics]
    mc: MonteCarloReport | None
    artifacts_path: str


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 — fixed argv, provenance only
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()[:12]
    except Exception:
        return "unknown"


def regime_sharpes(
    result: BacktestResult, snapshots_features: dict[date, float], capital: float
) -> dict[str, float]:
    """Daily-PnL Sharpe per VIX-percentile regime bucket. Days without a
    feature value fall into 'unknown' (counted, not hidden)."""
    import math

    import numpy as np

    buckets: dict[str, list[float]] = {"low": [], "mid": [], "high": [], "unknown": []}
    for day, pnl in result.daily_pnl.items():
        pct = snapshots_features.get(day)
        if pct is None:
            buckets["unknown"].append(float(pnl))
        elif pct < 30:
            buckets["low"].append(float(pnl))
        elif pct <= 70:
            buckets["mid"].append(float(pnl))
        else:
            buckets["high"].append(float(pnl))
    out: dict[str, float] = {}
    for name, pnls in buckets.items():
        if len(pnls) < 15:
            continue  # too few days to score a regime
        arr = np.asarray(pnls) / capital
        std = float(np.std(arr, ddof=1))
        if std > 1e-12:
            out[name] = float(np.mean(arr) / std * math.sqrt(252))
    return out


def _write_artifacts(
    root: Path, run_id: str, results: dict[FillScenario, BacktestResult], summary: dict[str, Any]
) -> Path:
    out_dir = root / "backtests" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for scenario, result in results.items():
        with (out_dir / f"trades_{scenario.value.lower()}.csv").open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["ts", "instrument_id", "side", "qty", "price", "costs", "tag", "realized_pnl"]
            )
            for t in result.trades:
                writer.writerow(
                    [
                        t.ts.isoformat(),
                        t.instrument_id,
                        t.side,
                        t.qty,
                        t.price,
                        t.costs,
                        t.tag,
                        t.realized_pnl,
                    ]
                )
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return out_dir


async def run_experiment(
    db: Database,
    strategy_factory: Any,  # Callable[[], Strategy] — fresh instance per scenario
    snapshots_by_scenario: Any,  # Callable[[], Iterable[MarketState]] — fresh iterator
    hypothesis: str,
    params: dict[str, Any],
    data_range: tuple[date, date],
    dataset_version: str,
    capital: float = 1_000_000.0,
    vix_percentile_by_day: dict[date, float] | None = None,
    walkforward_oos: Metrics | None = None,
    datalake_root: Path = Path("datalake"),
    synthetic_spread_pct: float | None = None,
) -> ExperimentOutcome:
    from decimal import Decimal

    run_id = str(uuid4())
    results: dict[FillScenario, BacktestResult] = {}
    metrics: dict[FillScenario, Metrics] = {}

    for scenario in FillScenario:
        strategy: Strategy = strategy_factory()
        config = BacktestConfig(
            scenario=scenario,
            capital=Decimal(str(capital)),
            dataset_version=dataset_version,
            synthetic_spread_pct=synthetic_spread_pct,
        )
        states: list[MarketState] = list(snapshots_by_scenario())
        results[scenario] = run_backtest(strategy, states, config)
        metrics[scenario] = compute_metrics(results[scenario])

    expected = results[FillScenario.EXPECTED]
    mc = monte_carlo(trade_pnls(expected), method="block", seed=42)
    regimes = regime_sharpes(expected, vix_percentile_by_day or {}, capital)

    verdict = evaluate(
        expected_metrics=metrics[FillScenario.EXPECTED],
        capital=capital,
        mc=mc,
        walkforward_oos_metrics=walkforward_oos,
        regime_sharpes=regimes,
    )

    summary: dict[str, Any] = {
        "run_id": run_id,
        "hypothesis": hypothesis,
        "params": params,
        "dataset_version": dataset_version,
        "synthetic_spread_pct": synthetic_spread_pct,
        "verdict": verdict.summary(),
        "metrics": {s.value: m.as_dict() for s, m in metrics.items()},
        "monte_carlo": mc.as_dict() if mc else None,
        "regime_sharpes": regimes,
    }
    artifacts = _write_artifacts(datalake_root, run_id, results, summary)

    trial = await ExperimentRepo(db).record(
        run_id=run_id,
        kind="BACKTEST",
        hypothesis=hypothesis,
        strategy=strategy_factory().name,
        params=params,
        data_range=data_range,
        cost_multiplier=1.5,  # judged scenario's slippage multiplier
        git_sha=git_sha(),
        metrics={
            "expected": metrics[FillScenario.EXPECTED].as_dict(),
            "best": metrics[FillScenario.BEST].as_dict(),
            "worst": metrics[FillScenario.WORST].as_dict(),
            "accepted": verdict.accepted,
            "failed_gates": [g.name for g in verdict.failures],
        },
        artifacts_path=str(artifacts),
    )
    return ExperimentOutcome(
        run_id=run_id,
        trial_number=trial,
        verdict=verdict,
        metrics_by_scenario=metrics,
        mc=mc,
        artifacts_path=str(artifacts),
    )
