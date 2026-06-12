"""Daily burn-in verification: one command, one GREEN/YELLOW/RED board.

Usage:
    docker compose run --rm api python scripts/burnin_check.py [--date 2026-06-13]

Grading logic lives in tp_research.burnin (shared with the console API).
Exit code: 0 = GREEN, 1 = YELLOW, 2 = RED — usable from cron/CI.
"""

import argparse
import asyncio
import sys
from datetime import date, datetime

from tp_research.burnin import overall, run_checks

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.timeutils import IST


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
