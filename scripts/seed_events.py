"""Seed the events table from a curated CSV. Idempotent: (event_ts, event_type)
pairs already present are skipped. Rows whose description still contains
'VERIFY' are rejected — unverified event times corrupt every downstream study.

Usage: uv run python scripts/seed_events.py docs/data/events.csv
"""

import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.db.orm import EventRow
from tp_core.timeutils import IST

VALID_TYPES = {"RBI_MPC", "BUDGET", "FOMC", "US_CPI", "IN_CPI", "HOLIDAY", "EXPIRY", "OTHER"}


def load_rows(path: Path) -> list[tuple[datetime, str, str]]:
    rows: list[tuple[datetime, str, str]] = []
    rejected = 0
    with path.open() as f:
        reader = csv.DictReader(line for line in f if not line.startswith("#"))
        for record in reader:
            description = record["description"].strip()
            if "VERIFY" in description.upper():
                rejected += 1
                continue
            event_type = record["event_type"].strip()
            if event_type not in VALID_TYPES:
                raise ValueError(f"unknown event_type: {event_type}")
            ts = datetime.strptime(record["event_ts"].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=IST)
            rows.append((ts, event_type, description))
    if rejected:
        print(f"rejected {rejected} unverified row(s) — verify dates and remove the flag")  # noqa: T201
    return rows


async def seed(path: Path) -> None:
    db = Database(get_settings())
    rows = load_rows(path)
    inserted = skipped = 0
    async with db.session() as s:
        for ts, event_type, description in rows:
            existing = await s.execute(
                select(EventRow.event_id).where(
                    EventRow.event_ts == ts, EventRow.event_type == event_type
                )
            )
            if existing.scalar_one_or_none() is not None:
                skipped += 1
                continue
            s.add(
                EventRow(
                    event_ts=ts, event_type=event_type, scheduled=True, description=description
                )
            )
            inserted += 1
    await db.close()
    print(f"events seeded: {inserted} inserted, {skipped} already present")  # noqa: T201


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data/events.csv")
    asyncio.run(seed(target))
