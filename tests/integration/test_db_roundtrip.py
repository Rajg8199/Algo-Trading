"""Round-trip tests against real Postgres (CI service container or local).
Run with: uv run pytest -m integration"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tp_core.config import Settings
from tp_core.db import Database
from tp_core.db.repos import InstrumentRepo, MarketDataRepo
from tp_core.models import Exchange, Instrument, Segment, Tick

pytestmark = pytest.mark.integration


@pytest.fixture
async def db() -> Database:
    database = Database(Settings())
    yield database
    await database.close()


async def test_instrument_upsert_idempotent(db: Database) -> None:
    repo = InstrumentRepo(db)
    instrument = Instrument(
        upstox_key="TEST_INDEX|RoundTrip",
        exchange=Exchange.NSE,
        segment=Segment.INDEX,
        underlying="NIFTY",
    )
    assert await repo.upsert_many([instrument]) == 1
    assert await repo.upsert_many([instrument]) == 1  # second time: update path
    mapping = await repo.by_upstox_keys(["TEST_INDEX|RoundTrip"])
    assert "TEST_INDEX|RoundTrip" in mapping


async def test_tick_insert_dedup(db: Database) -> None:
    instruments = InstrumentRepo(db)
    await instruments.upsert_many(
        [
            Instrument(
                upstox_key="TEST_INDEX|Ticks",
                exchange=Exchange.NSE,
                segment=Segment.INDEX,
                underlying="NIFTY",
            )
        ]
    )
    iid = (await instruments.by_upstox_keys(["TEST_INDEX|Ticks"]))["TEST_INDEX|Ticks"]
    market_data = MarketDataRepo(db)
    ts = datetime(2026, 6, 11, 5, 0, tzinfo=UTC)
    tick = Tick(ts=ts, instrument_id=iid, ltp=Decimal("24500.00"))
    await market_data.insert_ticks([tick])
    await market_data.insert_ticks([tick])  # duplicate PK silently skipped
    assert await market_data.last_tick_ts(iid) == ts
