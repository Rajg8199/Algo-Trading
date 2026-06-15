"""EXP-001-EOD runner — Conditional VRP screened on free EOD bhavcopy.

A COARSE SCREEN, not validation. Registered protocol:
docs/research/vrp-experiment-001-eod.md. Differences from the intraday
run_vrp_experiment.py (and ONLY these):
  - dataset filtered to the NSEBHAV source (one data origin, never mixed);
  - decision window widened to 15:25-15:35 to admit the 15:30 settlement snap;
  - fills use a synthetic spread (bhavcopy has no bid/ask) — PROVISIONAL until
    calibrated from recorded spreads; pass --synthetic-spread-pct;
  - regime variable is iv_percentile_1y (no India VIX loaded) — a proxy;
  - preflight drops the dq_checks gate (that job runs on recorded data).

A PASS here only justifies acquiring intraday data; it NEVER advances a
strategy toward paper/live. The decision is recorded as a SCREEN result.

Usage:
    uv run python scripts/run_vrp_experiment_eod.py --start 2025-01-01 --end 2026-06-12 \\
        --synthetic-spread-pct 2.0
"""

import argparse
import asyncio
import json
import sys
from datetime import date, time, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from tp_backtest.dataset import dataset_fingerprint, replay_snapshots
from tp_backtest.experiment import git_sha
from tp_backtest.fills import FillScenario
from tp_backtest.orchestrate import run_experiment_001
from tp_backtest.strategies.vrp import VRPParams

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.db.repos import ExperimentRepo
from tp_core.strategy import MarketState
from tp_core.timeutils import IST

HYPOTHESIS = "H1-VRP-EXP001-EOD"
SOURCE = "NSEBHAV"
MIN_DAYS = 120
EOD_DECISION_START = time(15, 25)
EOD_DECISION_END = time(15, 35)

EVENT_DAYS_SQL = text("""
    SELECT DISTINCT event_ts::date FROM events
    WHERE event_type IN ('RBI_MPC','BUDGET','FOMC','US_CPI','IN_CPI')
""")

# No India VIX loaded for the EOD screen — iv_percentile_1y is the regime proxy.
REGIME_PCT_SQL = text("""
    SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date, value FROM feature_values
    WHERE feature_name = 'iv_percentile_1y' AND entity = 'NIFTY' AND value IS NOT NULL
""")

PRIOR_TRIALS_SQL = text("SELECT count(*) FROM experiments WHERE hypothesis = :hypothesis")

# Entry-filter funnel at the registered grid's LEAST-restrictive thresholds
# (min VRP, min IV pctile, max vov, contango required) — the upper bound on
# entry days. Makes a zero-trade screen explain itself.
FUNNEL_SQL = text("""
WITH f AS (
  SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date d, feature_name, value
  FROM feature_values WHERE entity='NIFTY'
    AND feature_name IN ('atm_iv_front','har_rv_forecast_1d','iv_percentile_1y',
                         'vov_20d','term_slope')),
p AS (SELECT d,
    max(value) FILTER (WHERE feature_name='atm_iv_front') iv,
    max(value) FILTER (WHERE feature_name='har_rv_forecast_1d') rv,
    max(value) FILTER (WHERE feature_name='iv_percentile_1y') ivp,
    max(value) FILTER (WHERE feature_name='vov_20d') vov,
    max(value) FILTER (WHERE feature_name='term_slope') slope FROM f GROUP BY d)
SELECT
  count(*) FILTER (WHERE iv IS NOT NULL AND rv IS NOT NULL AND ivp IS NOT NULL
                     AND vov IS NOT NULL AND slope IS NOT NULL) AS s0,
  count(*) FILTER (WHERE iv-rv >= :vrp) AS s1,
  count(*) FILTER (WHERE iv-rv >= :vrp AND ivp >= :ivp) AS s2,
  count(*) FILTER (WHERE iv-rv >= :vrp AND ivp >= :ivp AND slope >= 0) AS s3,
  count(*) FILTER (WHERE iv-rv >= :vrp AND ivp >= :ivp AND slope >= 0 AND vov <= :vov) AS s4
FROM p WHERE d BETWEEN :start AND :end
""")


async def entry_funnel(db: Database, start: date, end: date) -> list[dict[str, object]]:
    from tp_backtest.orchestrate import REGISTERED_GRID

    vrp = min(REGISTERED_GRID["min_vrp_points"])  # type: ignore[type-var]
    ivp = min(REGISTERED_GRID["min_iv_percentile"])  # type: ignore[type-var]
    vov = max(REGISTERED_GRID["max_vov"])  # type: ignore[type-var]
    async with db.session() as s:
        r = (
            await s.execute(
                FUNNEL_SQL, {"vrp": vrp, "ivp": ivp, "vov": vov, "start": start, "end": end}
            )
        ).one()
    return [
        {"label": "feature-complete days", "days": int(r.s0)},
        {"label": f"VRP ≥ {vrp}", "days": int(r.s1)},
        {"label": f"IV pctile ≥ {ivp:g}", "days": int(r.s2)},
        {"label": "contango (slope ≥ 0)", "days": int(r.s3)},
        {"label": f"vov ≤ {vov}", "days": int(r.s4)},
    ]


def _p(message: str) -> None:
    print(message)  # noqa: T201 — research CLI output


async def preflight(db: Database, start: date, end: date) -> tuple[bool, list[str]]:
    problems: list[str] = []
    async with db.session() as s:
        days = (
            await s.execute(
                text("""SELECT count(DISTINCT (oc.ts AT TIME ZONE 'Asia/Kolkata')::date)
                        FROM option_chain oc JOIN instruments i USING (instrument_id)
                        WHERE i.underlying='NIFTY' AND split_part(i.upstox_key,'|',1)=:src
                          AND oc.ts BETWEEN :s AND :e"""),
                {"src": SOURCE, "s": start, "e": end + timedelta(days=1)},
            )
        ).scalar()
    _p(f"preflight: source={SOURCE} bhav_chain_days={days}")
    if (days or 0) < MIN_DAYS:
        problems.append(f"only {days} bhav chain days; need >= {MIN_DAYS}")
    return not problems, problems


async def main(start: date, end: date, capital: float, spread_pct: float) -> int:
    db = Database(get_settings())
    try:
        ok, problems = await preflight(db, start, end)
        if not ok:
            _p("PREFLIGHT ABORT — no trial burned:")
            for problem in problems:
                _p(f"  - {problem}")
            return 2

        dataset_version = await dataset_fingerprint(db, ["NIFTY"], start, end, source=SOURCE)
        async with db.session() as s:
            event_days = frozenset(d for (d,) in (await s.execute(EVENT_DAYS_SQL)).all())
            regime_pct = {d: float(v) for d, v in (await s.execute(REGIME_PCT_SQL)).all()}
            prior = int(
                (await s.execute(PRIOR_TRIALS_SQL, {"hypothesis": HYPOTHESIS})).scalar() or 0
            )

        _p(f"loading NSEBHAV snapshots {start}..{end} (dataset {dataset_version})")
        states_by_day: dict[date, list[MarketState]] = {}
        async for state in replay_snapshots(db, ["NIFTY"], start, end, source=SOURCE):
            states_by_day.setdefault(state.ts.astimezone(IST).date(), []).append(state)
        _p(
            f"loaded {sum(len(v) for v in states_by_day.values())} snapshots across "
            f"{len(states_by_day)} days; synthetic_spread_pct={spread_pct} (PROVISIONAL); "
            "running registered 72-combo protocol"
        )

        funnel = await entry_funnel(db, start, end)
        _p(f"entry funnel: {' → '.join(str(s['days']) for s in funnel)}")
        base = VRPParams(decision_start=EOD_DECISION_START, decision_end=EOD_DECISION_END)
        report = run_experiment_001(
            states_by_day=states_by_day,
            event_days=event_days,
            vix_percentile_by_day=regime_pct,  # iv_percentile_1y proxy
            capital=capital,
            dataset_version=dataset_version,
            prior_trials=prior,
            base_params=base,
            synthetic_spread_pct=spread_pct,
        )

        run_id = str(uuid4())
        out_dir = Path(get_settings().datalake_root) / "backtests" / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "hypothesis": HYPOTHESIS,
                    "screen": True,
                    "synthetic_spread_pct": spread_pct,
                    "dataset_version": dataset_version,
                    "entry_funnel": funnel,
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
            params={
                "grid": "registered-72",
                "protocol": "vrp-experiment-001-eod",
                "screen": True,
                "decision_window": f"{EOD_DECISION_START}-{EOD_DECISION_END}",
                "synthetic_spread_pct": spread_pct,
                "source": SOURCE,
            },
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
        _p("=== EXP-001-EOD SCREEN (NOT validation; a PASS only justifies buying intraday) ===")
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
    parser.add_argument(
        "--synthetic-spread-pct",
        type=float,
        default=2.0,
        help="PROVISIONAL full spread as %% of mid for quote-less fills; calibrate from "
        "recorded spreads before trusting results (default 2.0)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.start, args.end, args.capital, args.synthetic_spread_pct)))
