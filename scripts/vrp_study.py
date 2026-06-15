"""Measure the volatility-risk premium on NIFTY (or SENSEX) from EOD data.

    uv run python scripts/vrp_study.py [--underlying NIFTY] [--horizon 5]

Answers: is ATM IV > forward realised vol, by how much, and is it bigger when
IV is high? Foundational read before any short-vol strategy. Host runs need
POSTGRES_HOST=localhost.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from sqlalchemy import text
from tp_research.options.vrp import compute_vrp, summarize_vrp

from tp_core.config import get_settings
from tp_core.db import Database

_CAL_SQL = text("""
    SELECT t.ts::date AS d, last(t.ltp, t.ts) AS c
    FROM ticks t JOIN instruments i USING (instrument_id)
    WHERE i.underlying = :u AND i.segment = 'INDEX' AND i.upstox_key LIKE 'NSEBHAV%'
    GROUP BY d ORDER BY d
""")
_IV_SQL = text("""
    SELECT ts::date AS d, value
    FROM feature_values
    WHERE entity = :u AND feature_name = 'atm_iv_front' AND value IS NOT NULL
    ORDER BY ts
""")


def _p(m: str) -> None:
    print(m, flush=True)  # noqa: T201 — analysis CLI


async def main() -> int:
    ap = argparse.ArgumentParser(description="VRP measurement study")
    ap.add_argument("--underlying", default="NIFTY")
    ap.add_argument("--horizon", type=int, default=5, help="forward realised-vol horizon (days)")
    args = ap.parse_args()

    db = Database(get_settings())
    try:
        async with db.session() as s:
            cal_rows = (await s.execute(_CAL_SQL, {"u": args.underlying})).all()
            iv_rows = (await s.execute(_IV_SQL, {"u": args.underlying})).all()
        calendar: list[tuple[date, float]] = [(d, float(c)) for d, c in cal_rows if c is not None]
        iv_by_day = {d: float(v) for d, v in iv_rows}

        for horizon in (args.horizon, 10, 21):
            points = compute_vrp(calendar, iv_by_day, horizon=horizon)
            summ = summarize_vrp(points)
            _p("")
            _p(f"=== VRP — {args.underlying}, {horizon}-day forward realised vol ===")
            if summ is None:
                _p("  insufficient data")
                continue
            _p(f"  days            {summ.n}")
            _p(f"  mean ATM IV     {summ.mean_iv:.1f}%")
            _p(f"  mean fwd RV     {summ.mean_fwd_rv:.1f}%")
            _p(f"  mean VRP        {summ.mean_vrp:+.2f} vol pts   (median {summ.median_vrp:+.2f})")
            _p(f"  hit rate        {summ.hit_rate * 100:.0f}% of days IV > forward RV")
            _p(f"  info ratio      {summ.info_ratio:.2f}  (mean/std of daily VRP)")
            _p("  by IV regime:")
            for label, n, mv in summ.by_iv_tercile:
                _p(f"    {label:<8} {n:>4} days   mean VRP {mv:+.2f}")
    finally:
        await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
