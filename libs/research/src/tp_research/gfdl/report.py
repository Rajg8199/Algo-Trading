"""Import + readiness reporting.

ImportReport: what happened (rows, rejects, throughput, gaps).
ReadinessReport: is the imported history safe for Experiment 001 — the
preflight criteria, evaluated against the database, with PASS/FAIL per item.
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from tp_core.db import Database
from tp_research.gfdl.importer import FileResult


@dataclass
class ImportReport:
    batch_id: str
    results: list[FileResult] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        done = [r for r in self.results if r.status == "done"]
        failed = [r for r in self.results if r.status != "done"]
        rejects: dict[str, int] = {}
        for r in self.results:
            for reason, n in r.rejected_by_reason.items():
                rejects[reason] = rejects.get(reason, 0) + n
        seconds = sum(r.seconds for r in self.results)
        imported = sum(r.rows_imported for r in done)
        return {
            "batch_id": self.batch_id,
            "files_done": len(done),
            "files_failed": len(failed),
            "failed_files": [{"path": r.path, "error": r.error} for r in failed[:20]],
            "rows_total": sum(r.rows_total for r in self.results),
            "rows_imported": imported,
            "rows_rejected": sum(r.rows_rejected for r in self.results),
            "rejected_by_reason": rejects,
            "options_without_spot": sum(r.options_without_spot for r in self.results),
            "benchmark": {
                "wall_seconds_sum": round(seconds, 1),
                "rows_per_second": round(imported / seconds, 0) if seconds else None,
            },
        }

    def write(self, root: Path) -> Path:
        out = root / "imports" / self.batch_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(self.summary(), indent=2))
        return out


async def coverage_gaps(
    db: Database, underlying: str, start: date, end: date, holidays: frozenset[date]
) -> dict[str, Any]:
    """Missing trading dates / expiries / strike coverage for one underlying."""
    async with db.session() as s:
        day_rows = (
            await s.execute(
                text("""SELECT DISTINCT (oc.ts AT TIME ZONE 'Asia/Kolkata')::date
                        FROM option_chain oc JOIN instruments i USING (instrument_id)
                        WHERE i.underlying = :u AND oc.ts BETWEEN :s AND :e"""),
                {"u": underlying, "s": start, "e": end + timedelta(days=1)},
            )
        ).all()
        expiry_rows = (
            await s.execute(
                text("""SELECT DISTINCT i.expiry FROM option_chain oc
                        JOIN instruments i USING (instrument_id)
                        WHERE i.underlying = :u AND i.expiry IS NOT NULL
                          AND oc.ts BETWEEN :s AND :e"""),
                {"u": underlying, "s": start, "e": end + timedelta(days=1)},
            )
        ).all()
        strike_stats = (
            await s.execute(
                text("""SELECT i.expiry, count(DISTINCT i.strike) AS n_strikes
                        FROM option_chain oc JOIN instruments i USING (instrument_id)
                        WHERE i.underlying = :u AND oc.ts BETWEEN :s AND :e
                        GROUP BY i.expiry ORDER BY i.expiry"""),
                {"u": underlying, "s": start, "e": end + timedelta(days=1)},
            )
        ).all()

    observed_days = {r[0] for r in day_rows}
    expected_days = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5 and cursor not in holidays:
            expected_days.append(cursor)
        cursor += timedelta(days=1)
    missing_days = sorted(set(expected_days) - observed_days)

    thin_expiries = [{"expiry": str(e), "strikes": int(n)} for e, n in strike_stats if int(n) < 20]
    return {
        "underlying": underlying,
        "expected_trading_days": len(expected_days),
        "observed_days": len(observed_days),
        "missing_days": [str(d) for d in missing_days],
        "expiries_observed": len(expiry_rows),
        "thin_expiries": thin_expiries,
    }


async def readiness_report(
    db: Database, start: date, end: date, holidays: frozenset[date]
) -> dict[str, Any]:
    """Experiment-001 readiness: PASS/FAIL per preflight criterion."""
    checks: list[dict[str, Any]] = []

    async with db.session() as s:
        nifty_days = (
            await s.execute(
                text("""SELECT count(DISTINCT (oc.ts AT TIME ZONE 'Asia/Kolkata')::date)
                        FROM option_chain oc JOIN instruments i USING (instrument_id)
                        WHERE i.underlying = 'NIFTY'"""),
            )
        ).scalar() or 0
        iv_cov = (
            await s.execute(
                text("""SELECT 100.0 * count(oc.iv) / nullif(count(*), 0)
                        FROM option_chain oc JOIN instruments i USING (instrument_id)
                        WHERE i.underlying = 'NIFTY' AND oc.spot IS NOT NULL
                          AND i.strike BETWEEN oc.spot * 0.95 AND oc.spot * 1.05"""),
            )
        ).scalar()
        spot_cov = (
            await s.execute(
                text("""SELECT 100.0 * count(oc.spot) / nullif(count(*), 0)
                        FROM option_chain oc JOIN instruments i USING (instrument_id)
                        WHERE i.underlying = 'NIFTY'"""),
            )
        ).scalar()

    gaps = await coverage_gaps(db, "NIFTY", start, end, holidays)

    checks.append(
        {
            "name": "preflight_days",
            "passed": int(nifty_days) >= 120,
            "detail": f"{nifty_days} NIFTY chain days (need >= 120)",
        }
    )
    checks.append(
        {
            "name": "missing_days",
            "passed": len(gaps["missing_days"]) <= 5,
            "detail": f"{len(gaps['missing_days'])} missing trading days (allow <= 5, "
            "each must be explained)",
        }
    )
    checks.append(
        {
            "name": "near_atm_iv_coverage",
            "passed": iv_cov is not None and float(iv_cov) >= 90.0,
            "detail": f"{float(iv_cov):.1f}% near-ATM rows have computed IV"
            if iv_cov is not None
            else "no data",
        }
    )
    checks.append(
        {
            "name": "spot_join_coverage",
            "passed": spot_cov is not None and float(spot_cov) >= 95.0,
            "detail": f"{float(spot_cov):.1f}% option rows joined to spot"
            if spot_cov is not None
            else "no data",
        }
    )
    checks.append(
        {
            "name": "thin_expiries",
            "passed": len(gaps["thin_expiries"]) == 0,
            "detail": f"{len(gaps['thin_expiries'])} expiries with < 20 strikes",
        }
    )
    checks.append(
        {
            "name": "synthetic_spread_blocker",
            "passed": False,
            "detail": "vendor bars have no bid/ask: Experiment 001 on this data requires "
            "BacktestConfig.synthetic_spread_pct, calibrated from recorded spreads "
            "(registered amendment) — flip manually once calibrated",
        }
    )
    return {
        "range": [str(start), str(end)],
        "ready": all(c["passed"] for c in checks),
        "checks": checks,
        "coverage": gaps,
        "iv_source": "computed Black-Scholes (rate 6.5%), not vendor-supplied",
    }
