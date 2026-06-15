"""Historical feature backfill — drives the per-day feature engine across a
date range so feature_values has the history a backtest reads.

The engine computes each feature from data STRICTLY BEFORE the trade date
(no same-day leakage, no backfilled fakes), so days are processed oldest
first and percentile/HAR/rank features only become non-null once enough
history has accumulated (≈1 year for iv_percentile_1y).

    uv run python scripts/backfill_features.py --start 2025-06-13 --end 2026-06-12

With no range, uses the min/max option_chain date present.
"""

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import text
from tp_research.features.engine import run_feature_engine

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.db.repos import EventsRepo


def _p(message: str) -> None:
    print(message)  # noqa: T201 — ops CLI


async def _data_range(db: Database) -> tuple[date, date] | None:
    async with db.session() as s:
        row = (
            await s.execute(
                text(
                    "SELECT (min(ts) AT TIME ZONE 'Asia/Kolkata')::date, "
                    "(max(ts) AT TIME ZONE 'Asia/Kolkata')::date FROM option_chain"
                )
            )
        ).one()
    return (row[0], row[1]) if row[0] else None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="ISO date; default = earliest option_chain date")
    parser.add_argument("--end", help="ISO date; default = latest option_chain date")
    parser.add_argument(
        "--close-cut",
        default="15:31",
        help="IST close cut HH:MM (default 15:31 = admits the 15:30 EOD settlement "
        "snapshot; 15:25 = intraday-recorded behavior)",
    )
    args = parser.parse_args()
    close_cut = datetime.strptime(args.close_cut, "%H:%M").time()  # noqa: DTZ007 — time-of-day only

    db = Database(get_settings())
    try:
        if args.start and args.end:
            start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
        else:
            rng = await _data_range(db)
            if rng is None:
                _p("no option_chain data — load bhavcopy first")
                return 1
            start, end = rng
        holidays = await EventsRepo(db).holidays()
        _p(f"backfilling features {start} .. {end} (holidays excluded: {len(holidays)})")

        cursor = start
        days = computed_days = 0
        total_computed = total_skipped = total_failed = 0
        cur_pct = 0.0
        while cursor <= end:
            if cursor.weekday() < 5 and cursor not in holidays:
                summary = await run_feature_engine(db, cursor, close_cut=close_cut)
                days += 1
                total_computed += summary.computed
                total_skipped += summary.skipped
                total_failed += summary.failed
                if summary.computed:
                    computed_days += 1
                    cur_pct = summary.coverage_pct
                if days % 20 == 0:
                    _p(
                        f"  {cursor}: days={days} last_coverage={cur_pct:.0f}% "
                        f"computed={total_computed} skipped={total_skipped} failed={total_failed}"
                    )
            cursor += timedelta(days=1)

        _p(
            f"DONE days_processed={days} days_with_features={computed_days} "
            f"computed={total_computed} skipped={total_skipped} failed={total_failed}"
        )
        return 0 if total_failed == 0 else 1
    finally:
        await db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
