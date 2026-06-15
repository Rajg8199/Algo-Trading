"""Import + EOD readiness reporting for bhavcopy data.

Mirrors gfdl.report but (a) filters strictly to bhavcopy-sourced instruments
(synthetic-key namespace NSEBHAV/BSEBHAV) so it never mixes data sources, and
(b) replaces GFDL's synthetic_spread_blocker with an EOD-granularity blocker:
this data has one snapshot/contract/day and no bid/ask, so it gates the
intraday Experiment 001 and is releasable only against EXP-001-EOD.
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from tp_core.db import Database
from tp_research.bhav.importer import BhavFileResult

SOURCE_TAGS = ("NSEBHAV", "BSEBHAV")
_SRC_FILTER = "split_part(i.upstox_key, '|', 1) = ANY(:tags)"


@dataclass
class ImportReport:
    batch_id: str
    results: list[BhavFileResult] = field(default_factory=list)

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
            "rows_selected": sum(r.selected for r in self.results),
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
    params = {"u": underlying, "s": start, "e": end + timedelta(days=1), "tags": list(SOURCE_TAGS)}
    async with db.session() as s:
        day_rows = (
            await s.execute(
                text(f"""SELECT DISTINCT (oc.ts AT TIME ZONE 'Asia/Kolkata')::date
                         FROM option_chain oc JOIN instruments i USING (instrument_id)
                         WHERE i.underlying = :u AND {_SRC_FILTER}
                           AND oc.ts BETWEEN :s AND :e"""),
                params,
            )
        ).all()
        expiry_rows = (
            await s.execute(
                text(f"""SELECT DISTINCT i.expiry FROM option_chain oc
                         JOIN instruments i USING (instrument_id)
                         WHERE i.underlying = :u AND i.expiry IS NOT NULL AND {_SRC_FILTER}
                           AND oc.ts BETWEEN :s AND :e"""),
                params,
            )
        ).all()
        strike_stats = (
            await s.execute(
                text(f"""SELECT i.expiry, count(DISTINCT i.strike) AS n_strikes
                         FROM option_chain oc JOIN instruments i USING (instrument_id)
                         WHERE i.underlying = :u AND {_SRC_FILTER} AND oc.ts BETWEEN :s AND :e
                         GROUP BY i.expiry ORDER BY i.expiry"""),
                params,
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
    """EXP-001-EOD readiness: PASS/FAIL per preflight criterion (NIFTY)."""
    checks: list[dict[str, Any]] = []
    tags = list(SOURCE_TAGS)

    async with db.session() as s:
        nifty_days = (
            await s.execute(
                text(f"""SELECT count(DISTINCT (oc.ts AT TIME ZONE 'Asia/Kolkata')::date)
                         FROM option_chain oc JOIN instruments i USING (instrument_id)
                         WHERE i.underlying = 'NIFTY' AND {_SRC_FILTER}"""),
                {"tags": tags},
            )
        ).scalar() or 0
        iv_cov = (
            await s.execute(
                text(f"""SELECT 100.0 * count(oc.iv) / nullif(count(*), 0)
                         FROM option_chain oc JOIN instruments i USING (instrument_id)
                         WHERE i.underlying = 'NIFTY' AND {_SRC_FILTER} AND oc.spot IS NOT NULL
                           AND i.strike BETWEEN oc.spot * 0.95 AND oc.spot * 1.05"""),
                {"tags": tags},
            )
        ).scalar()
        spot_cov = (
            await s.execute(
                text(f"""SELECT 100.0 * count(oc.spot) / nullif(count(*), 0)
                         FROM option_chain oc JOIN instruments i USING (instrument_id)
                         WHERE i.underlying = 'NIFTY' AND {_SRC_FILTER}"""),
                {"tags": tags},
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
            "detail": f"{float(spot_cov):.1f}% option rows carry an underlying price"
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
            "name": "eod_granularity_blocker",
            "passed": False,
            "detail": "bhavcopy is EOD settlement only — one snapshot/contract/day, no "
            "bid/ask. This data CANNOT run the intraday Experiment 001. It runs ONLY as "
            "EXP-001-EOD (daily entry/exit at settlement +/- modeled slippage). Flip this "
            "manually once the EXP-001-EOD protocol is registered in docs/research/.",
        }
    )
    return {
        "range": [str(start), str(end)],
        "ready": all(c["passed"] for c in checks),
        "checks": checks,
        "coverage": gaps,
        "iv_source": "computed Black-Scholes (rate 6.5%) from settlement price, not vendor",
        "granularity": "EOD settlement (no intraday, no bid/ask)",
    }
