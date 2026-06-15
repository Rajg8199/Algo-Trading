"""NSE cash-market (equity) EOD bhavcopy import CLI — feeds the breakout scanner.

Probe a single day first (always, on first contact):
    uv run python scripts/equity_bhav_import.py --probe 2026-06-12

Import one day:
    uv run python scripts/equity_bhav_import.py --date 2026-06-12

Backfill a range (skips weekends + unpublished/holiday days):
    uv run python scripts/equity_bhav_import.py --backfill 2024-01-01:2026-06-12

Import a local file (already downloaded .csv or .zip):
    uv run python scripts/equity_bhav_import.py --file /tmp/BhavCopy_NSE_CM_..._F_0000.csv.zip

Host runs need POSTGRES_HOST=localhost to override the container hostname in .env.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

from tp_research.equity.bhav import download_equity_bhav, probe_equity_bhav
from tp_research.equity.importer import import_bhav_file

from tp_core.config import get_settings
from tp_core.db import Database


def _p(msg: str) -> None:
    print(msg, flush=True)  # noqa: T201 — ops CLI; flush so background runs stream


def _d(s: str) -> date:
    return date.fromisoformat(s)


async def _probe(day: date) -> int:
    raw = await download_equity_bhav(day)
    pr = probe_equity_bhav(raw)
    _p(
        f"date={pr.trade_date} total_rows={pr.total_rows} "
        f"equity_rows={pr.equity_rows} parsed={pr.parse_ok}"
    )
    _p(f"sample={', '.join(pr.sample)}")
    return 0


async def _import_one(db: Database, day: date) -> int:
    raw = await download_equity_bhav(day)
    return await import_bhav_file(db, raw)


async def _backfill(db: Database, start: date, end: date) -> None:
    day = start
    total = 0
    days = 0
    while day <= end:
        if day.weekday() < 5:  # skip Sat/Sun
            try:
                n = await _import_one(db, day)
                total += n
                days += 1
                _p(f"  {day} imported {n} bars")
            except FileNotFoundError:
                _p(f"  {day} not published (holiday / not yet) — skipped")
            except Exception as exc:  # long run must survive transient network errors
                _p(f"  {day} ERROR ({type(exc).__name__}: {exc}) — skipped, re-run to fill")
        day += timedelta(days=1)
    _p(f"backfill done: {total} bars over {days} trading days")


async def main() -> int:
    ap = argparse.ArgumentParser(description="NSE equity bhavcopy import")
    ap.add_argument("--probe", metavar="YYYY-MM-DD", help="download a day and print a summary")
    ap.add_argument("--date", metavar="YYYY-MM-DD", help="import one day")
    ap.add_argument("--backfill", metavar="START:END", help="import an inclusive date range")
    ap.add_argument("--file", metavar="PATH", help="import a local .csv/.zip bhavcopy")
    args = ap.parse_args()

    if args.probe:
        return await _probe(_d(args.probe))

    db = Database(get_settings())
    try:
        if args.file:
            raw = Path(args.file).read_bytes()  # noqa: ASYNC240 — one-shot CLI, blocking read is fine
            n = await import_bhav_file(db, raw)
            _p(f"imported {n} bars from {args.file}")
        elif args.date:
            n = await _import_one(db, _d(args.date))
            _p(f"imported {n} bars for {args.date}")
        elif args.backfill:
            start_s, end_s = args.backfill.split(":", 1)
            await _backfill(db, _d(start_s), _d(end_s))
        else:
            ap.print_help()
            return 2
    finally:
        await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
