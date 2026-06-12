"""EXPERIMENT 001 runner — Conditional VRP on NIFTY weeklies.

Usage:
    uv run python scripts/run_vrp_experiment.py --start 2026-01-01 --end 2026-12-31

Inputs:   option_chain, instruments, feature_values, events, dq_checks
Outputs:  datalake/backtests/<run_id>/ (summary.json, surface.json)
          one experiments row (kind=BACKTEST, hypothesis=H1-VRP-EXP001)

Preflight aborts WITHOUT burning a trial if the data cannot support the
experiment. The registered protocol is docs/research/vrp-experiment-001.md;
this script implements it and nothing else.
"""

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from tp_backtest.dataset import dataset_fingerprint, replay_snapshots
from tp_backtest.experiment import git_sha
from tp_backtest.fills import FillScenario
from tp_backtest.orchestrate import run_experiment_001

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.db.repos import ExperimentRepo
from tp_core.strategy import MarketState
from tp_core.timeutils import IST

HYPOTHESIS = "H1-VRP-EXP001"
MIN_DAYS = 120
MIN_DQ_PASS_RATE = 0.95

DQ_RATE_SQL = text("""
    SELECT coalesce(avg(passed::int), 0) FROM dq_checks
    WHERE check_date BETWEEN :start AND :end
""")

EVENT_DAYS_SQL = text("""
    SELECT DISTINCT event_ts::date FROM events
    WHERE event_type IN ('RBI_MPC','BUDGET','FOMC','US_CPI','IN_CPI')
""")

VIX_PCT_SQL = text("""
    SELECT ts::date, value FROM feature_values
    WHERE feature_name = 'vix_percentile_1y' AND entity = 'NIFTY'
      AND value IS NOT NULL
""")

PRIOR_TRIALS_SQL = text("SELECT count(*) FROM experiments WHERE hypothesis = :hypothesis")


def _p(message: str) -> None:
    print(message)  # noqa: T201 — research CLI output


async def preflight(db: Database, start: date, end: date) -> tuple[bool, list[str]]:
    problems: list[str] = []
    fingerprint = await dataset_fingerprint(db, ["NIFTY"], start, end)
    async with db.session() as s:
        days = (
            await s.execute(
                text("""SELECT count(DISTINCT oc.ts::date) FROM option_chain oc
                        JOIN instruments i USING (instrument_id)
                        WHERE i.underlying='NIFTY' AND oc.ts BETWEEN :s AND :e"""),
                {"s": start, "e": end + timedelta(days=1)},
            )
        ).scalar()
        dq_rate = (await s.execute(DQ_RATE_SQL, {"start": start, "end": end})).scalar()
    _p(f"preflight: fingerprint={fingerprint} days={days} dq_pass_rate={float(dq_rate or 0):.2%}")
    if (days or 0) < MIN_DAYS:
        problems.append(f"only {days} trading days of chain data; need >= {MIN_DAYS}")
    if float(dq_rate or 0) < MIN_DQ_PASS_RATE:
        problems.append(f"DQ pass rate {float(dq_rate or 0):.2%} < {MIN_DQ_PASS_RATE:.0%}")
    return not problems, problems


async def main(start: date, end: date, capital: float) -> int:
    db = Database(get_settings())
    try:
        ok, problems = await preflight(db, start, end)
        if not ok:
            _p("PREFLIGHT ABORT — no trial burned:")
            for problem in problems:
                _p(f"  - {problem}")
            return 2

        dataset_version = await dataset_fingerprint(db, ["NIFTY"], start, end)
        async with db.session() as s:
            event_days = frozenset(d for (d,) in (await s.execute(EVENT_DAYS_SQL)).all())
            vix_pct = {d: float(v) for d, v in (await s.execute(VIX_PCT_SQL)).all()}
            prior = int(
                (await s.execute(PRIOR_TRIALS_SQL, {"hypothesis": HYPOTHESIS})).scalar() or 0
            )

        _p(f"loading snapshots {start}..{end} (dataset {dataset_version})")
        states_by_day: dict[date, list[MarketState]] = {}
        async for state in replay_snapshots(db, ["NIFTY"], start, end):
            states_by_day.setdefault(state.ts.astimezone(IST).date(), []).append(state)
        _p(
            f"loaded {sum(len(v) for v in states_by_day.values())} snapshots "
            f"across {len(states_by_day)} days; running 72-combo protocol"
        )

        report = run_experiment_001(
            states_by_day=states_by_day,
            event_days=event_days,
            vix_percentile_by_day=vix_pct,
            capital=capital,
            dataset_version=dataset_version,
            prior_trials=prior,
        )

        run_id = str(uuid4())
        out_dir = Path("datalake/backtests") / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "hypothesis": HYPOTHESIS,
                    "dataset_version": dataset_version,
                    "decision": report.decision.value,
                    "reasons": report.reasons,
                    "dsr": report.dsr,
                    "n_trials": report.n_trials,
                    "oos_metrics": {s.value: m.as_dict() for s, m in report.oos_metrics.items()},
                    "monte_carlo": report.mc.as_dict() if report.mc else None,
                    "regime_sharpes": report.regime_sharpes,
                },
                indent=2,
                default=str,
            )
        )
        (out_dir / "surface.json").write_text(
            json.dumps(report.in_sample_surface, indent=2, default=str)
        )

        expected = report.oos_metrics.get(FillScenario.EXPECTED)
        await ExperimentRepo(db).record(
            run_id=run_id,
            kind="BACKTEST",
            hypothesis=HYPOTHESIS,
            strategy="vrp_nifty",
            params={"grid": "registered-72", "protocol": "vrp-experiment-001"},
            data_range=(start, end),
            cost_multiplier=1.5,
            git_sha=git_sha(),
            metrics={
                "decision": report.decision.value,
                "reasons": report.reasons,
                "dsr": report.dsr,
                "n_trials": report.n_trials,
                "oos_expected": expected.as_dict() if expected else None,
            },
            artifacts_path=str(out_dir),
        )

        _p("")
        _p(report.summary())
        _p(f"artifacts: {out_dir}")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.start, args.end, args.capital)))
