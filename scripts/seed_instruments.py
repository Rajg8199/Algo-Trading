"""One-shot instrument master seed. Downloads the Upstox instrument file
(no auth token required — it's a public asset) and upserts our universe:
NIFTY/SENSEX/India VIX indices, futures, and options.

Usage:  uv run python scripts/seed_instruments.py
Docker: docker compose run --rm api python scripts/seed_instruments.py

Idempotent; the scheduler refreshes the same data daily at 08:35 IST.
"""

import asyncio
import sys

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.db.repos import InstrumentRepo
from tp_upstox.rest import download_instrument_master


def _p(message: str) -> None:
    print(message)  # noqa: T201 — ops CLI output


async def main() -> int:
    db = Database(get_settings())
    try:
        instruments = await download_instrument_master()
        if len(instruments) < 100:
            _p(
                f"FAIL: parsed only {len(instruments)} instruments — "
                "check the master URL/format before proceeding"
            )
            return 1
        count = await InstrumentRepo(db).upsert_many(instruments)
        by_segment: dict[str, int] = {}
        for instrument in instruments:
            by_segment[instrument.segment.value] = by_segment.get(instrument.segment.value, 0) + 1
        _p(f"seeded {count} instruments: {by_segment}")
        index_count = by_segment.get("INDEX", 0)
        if index_count < 3:
            _p(
                f"WARNING: only {index_count}/3 index instruments found "
                "(need NIFTY, SENSEX, India VIX) — recorder subscriptions will be incomplete"
            )
            return 1
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
