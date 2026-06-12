"""Daily burn-in verification: one command, one GREEN/YELLOW/RED board.

Usage:
    docker compose run --rm api python scripts/burnin_check.py [--date 2026-06-13]

Reads ticks, option_chain, feature_values, dq_checks, data_gaps and grades
the day against the burn-in thresholds (docs/burn-in-plan.md). Exit code:
0 = GREEN, 1 = YELLOW, 2 = RED — usable from cron/CI.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import text

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.timeutils import IST

UNDERLYINGS = ("NIFTY", "SENSEX")


@dataclass
class Grade:
    name: str
    status: str  # GREEN | YELLOW | RED | N/A
    detail: str


def _grade(
    name: str,
    value: float | None,
    green: float,
    yellow: float,
    higher_is_better: bool = True,
    fmt: str = "{:.1f}",
) -> Grade:
    if value is None:
        return Grade(name, "RED", "no data")
    if higher_is_better:
        status = "GREEN" if value >= green else ("YELLOW" if value >= yellow else "RED")
    else:
        status = "GREEN" if value <= green else ("YELLOW" if value <= yellow else "RED")
    return Grade(name, status, fmt.format(value))


async def run_checks(db: Database, day: date) -> list[Grade]:
    day_start = datetime.combine(day, time(9, 0), tzinfo=IST)
    day_end = datetime.combine(day, time(16, 0), tzinfo=IST)
    params = {"s": day_start, "e": day_end, "unders": list(UNDERLYINGS), "d": day}
    grades: list[Grade] = []

    async with db.session() as s:
        # ── volume per underlying ────────────────────────────────────────
        rows = (
            await s.execute(
                text("""
            SELECT i.underlying,
                   count(*) FILTER (WHERE tbl = 't') AS ticks,
                   count(*) FILTER (WHERE tbl = 'c') AS chain
            FROM (
              SELECT instrument_id, 't' AS tbl FROM ticks WHERE ts BETWEEN :s AND :e
              UNION ALL
              SELECT instrument_id, 'c' FROM option_chain WHERE ts BETWEEN :s AND :e
            ) x JOIN instruments i USING (instrument_id)
            WHERE i.underlying = ANY(:unders) GROUP BY 1"""),
                params,
            )
        ).all()
        volumes = {u: (t, c) for u, t, c in rows}
        for u in UNDERLYINGS:
            ticks, chain = volumes.get(u, (0, 0))
            grades.append(_grade(f"ticks_{u}", float(ticks), 100_000, 50_000, fmt="{:,.0f}"))
            grades.append(_grade(f"chain_rows_{u}", float(chain), 100_000, 30_000, fmt="{:,.0f}"))

        # ── snapshot minutes + max gap ───────────────────────────────────
        rows = (
            await s.execute(
                text("""
            WITH snaps AS (
              SELECT i.underlying, oc.ts,
                     extract(epoch FROM oc.ts - lag(oc.ts) OVER
                       (PARTITION BY i.underlying ORDER BY oc.ts)) AS gap_s
              FROM (SELECT DISTINCT instrument_id, ts FROM option_chain
                    WHERE ts BETWEEN :s AND :e) oc
              JOIN instruments i USING (instrument_id)
              WHERE i.underlying = ANY(:unders))
            SELECT underlying, count(DISTINCT ts), coalesce(max(gap_s), 0)
            FROM snaps GROUP BY 1"""),
                params,
            )
        ).all()
        snap = {u: (n, g) for u, n, g in rows}
        for u in UNDERLYINGS:
            n, gap = snap.get(u, (0, None))
            grades.append(_grade(f"snapshot_minutes_{u}", float(n), 350, 300, fmt="{:.0f}"))
            grades.append(
                _grade(
                    f"max_chain_gap_s_{u}",
                    float(gap) if gap is not None else None,
                    120,
                    180,
                    higher_is_better=False,
                    fmt="{:.0f}s",
                )
            )

        # ── greeks / IV / OI quality near ATM ────────────────────────────
        rows = (
            await s.execute(
                text("""
            SELECT i.underlying,
              100.0 * count(*) FILTER (WHERE oc.delta IS NOT NULL AND oc.iv IS NOT NULL)
                / nullif(count(*),0) AS greeks_pct,
              100.0 * count(*) FILTER (WHERE oc.iv IS NULL OR oc.iv <= 1 OR oc.iv >= 200)
                / nullif(count(*),0) AS bad_iv_pct,
              100.0 * count(oc.oi) / nullif(count(*),0) AS oi_pct
            FROM option_chain oc JOIN instruments i USING (instrument_id)
            WHERE oc.ts BETWEEN :s AND :e AND i.underlying = ANY(:unders)
              AND oc.spot IS NOT NULL
              AND i.strike BETWEEN oc.spot*0.97 AND oc.spot*1.03
            GROUP BY 1"""),
                params,
            )
        ).all()
        quality = {u: (g, b, o) for u, g, b, o in rows}
        for u in UNDERLYINGS:
            g, bad_iv, oi = quality.get(u, (None, None, None))
            grades.append(_grade(f"greeks_coverage_{u}", g, 95, 90, fmt="{:.1f}%"))
            grades.append(
                _grade(f"invalid_iv_atm_{u}", bad_iv, 2, 5, higher_is_better=False, fmt="{:.1f}%")
            )
            grades.append(_grade(f"oi_coverage_{u}", oi, 98, 95, fmt="{:.1f}%"))

        # ── disconnects / gaps ───────────────────────────────────────────
        n_gaps = (
            await s.execute(
                text("SELECT count(*) FROM data_gaps WHERE detected_at BETWEEN :s AND :e"), params
            )
        ).scalar() or 0
        grades.append(
            _grade("ws_gaps_today", float(n_gaps), 3, 10, higher_is_better=False, fmt="{:.0f}")
        )

        # ── DQ framework results ─────────────────────────────────────────
        dq = (
            await s.execute(
                text("""
            SELECT count(*) FILTER (WHERE NOT passed AND check_name LIKE 'completeness%')
                 + count(*) FILTER (WHERE NOT passed AND check_name LIKE 'missing_strikes%')
                 + count(*) FILTER (WHERE NOT passed AND check_name LIKE 'invalid_iv%') AS p1_fails,
                   count(*) FILTER (WHERE NOT passed) AS total_fails,
                   count(*) AS total
            FROM dq_checks WHERE check_date = :d"""),
                params,
            )
        ).one()
        if dq.total == 0:
            grades.append(Grade("dq_checks", "YELLOW", "validation job has not run yet (21:00)"))
        elif dq.p1_fails > 0:
            grades.append(Grade("dq_checks", "RED", f"{dq.p1_fails} P1-class failures"))
        elif dq.total_fails > 0:
            grades.append(Grade("dq_checks", "YELLOW", f"{dq.total_fails} P2 failures"))
        else:
            grades.append(Grade("dq_checks", "GREEN", f"{dq.total}/{dq.total} passed"))

        # ── feature coverage (history features wake up over weeks) ───────
        feats = dict(
            (
                await s.execute(
                    text("""
            SELECT entity, count(*) FROM feature_values
            WHERE ts::date = :d GROUP BY entity"""),
                    params,
                )
            ).all()
        )
        for u in UNDERLYINGS:
            grades.append(_grade(f"features_{u}", float(feats.get(u, 0)), 10, 6, fmt="{:.0f}"))

    return grades


def overall(grades: list[Grade]) -> str:
    statuses = {g.status for g in grades}
    if "RED" in statuses:
        return "RED"
    if "YELLOW" in statuses:
        return "YELLOW"
    return "GREEN"


async def main(day: date) -> int:
    db = Database(get_settings())
    try:
        grades = await run_checks(db, day)
    finally:
        await db.close()
    icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "N/A": "⚪"}
    print(f"BURN-IN CHECK — {day.isoformat()}")  # noqa: T201
    for g in grades:
        print(f"  {icon[g.status]} {g.name:28s} {g.detail}")  # noqa: T201
    status = overall(grades)
    print(f"OVERALL: {icon[status]} {status}")  # noqa: T201
    return {"GREEN": 0, "YELLOW": 1, "RED": 2}[status]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    target = args.date or datetime.now(IST).date()
    sys.exit(asyncio.run(main(target)))
