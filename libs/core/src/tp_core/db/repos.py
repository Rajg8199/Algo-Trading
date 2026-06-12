"""Repositories: the only code that writes SQL against the operational DB.

Services depend on these classes (constructor-injected with a Database),
never on sessions or ORM rows directly — keeps services testable with fakes.
"""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tp_core.db.engine import Database
from tp_core.db.orm import (
    AuthTokenRow,
    DataGapRow,
    DQCheckRow,
    EventRow,
    FeatureValueRow,
    InstrumentRow,
    OptionChainRow,
    TickRow,
    VolMetricsDailyRow,
)
from tp_core.models import ChainRow, Instrument, Tick


class InstrumentRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_many(self, instruments: list[Instrument]) -> int:
        """Idempotent bulk upsert from the daily instrument-master refresh."""
        if not instruments:
            return 0
        rows = [
            {
                "upstox_key": i.upstox_key,
                "exchange": i.exchange.value,
                "segment": i.segment.value,
                "underlying": i.underlying,
                "expiry": i.expiry,
                "strike": i.strike,
                "option_type": i.option_type.value if i.option_type else None,
                "lot_size": i.lot_size,
                "tick_size": i.tick_size,
                "is_active": i.is_active,
            }
            for i in instruments
        ]
        stmt = pg_insert(InstrumentRow).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["upstox_key"],
            set_={"lot_size": stmt.excluded.lot_size, "is_active": stmt.excluded.is_active},
        )
        async with self._db.session() as s:
            await s.execute(stmt)
        return len(rows)

    async def active_options(self, underlying: str, expiry: date) -> list[InstrumentRow]:
        async with self._db.session() as s:
            result = await s.execute(
                select(InstrumentRow).where(
                    InstrumentRow.underlying == underlying,
                    InstrumentRow.segment == "OPT",
                    InstrumentRow.expiry == expiry,
                    InstrumentRow.is_active.is_(True),
                )
            )
            return list(result.scalars())

    async def by_upstox_keys(self, keys: list[str]) -> dict[str, int]:
        """Map upstox instrument keys -> instrument_id for ingest paths."""
        if not keys:
            return {}
        async with self._db.session() as s:
            result = await s.execute(
                select(InstrumentRow.upstox_key, InstrumentRow.instrument_id).where(
                    InstrumentRow.upstox_key.in_(keys)
                )
            )
            return dict(result.tuples().all())

    async def expiries(self, underlying: str, after: date) -> list[date]:
        async with self._db.session() as s:
            result = await s.execute(
                select(InstrumentRow.expiry)
                .where(
                    InstrumentRow.underlying == underlying,
                    InstrumentRow.segment == "OPT",
                    InstrumentRow.expiry >= after,
                    InstrumentRow.is_active.is_(True),
                )
                .distinct()
                .order_by(InstrumentRow.expiry)
            )
            return [e for (e,) in result.all() if e is not None]


class MarketDataRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert_ticks(self, ticks: list[Tick]) -> int:
        if not ticks:
            return 0
        stmt = pg_insert(TickRow).values([t.model_dump() for t in ticks])
        stmt = stmt.on_conflict_do_nothing(index_elements=["instrument_id", "ts"])
        async with self._db.session() as s:
            await s.execute(stmt)
        return len(ticks)

    async def insert_chain_rows(self, rows: list[ChainRow]) -> int:
        if not rows:
            return 0
        stmt = pg_insert(OptionChainRow).values([r.model_dump() for r in rows])
        stmt = stmt.on_conflict_do_nothing(index_elements=["instrument_id", "ts"])
        async with self._db.session() as s:
            await s.execute(stmt)
        return len(rows)

    async def last_tick_ts(self, instrument_id: int) -> datetime | None:
        async with self._db.session() as s:
            result = await s.execute(
                select(func.max(TickRow.ts)).where(TickRow.instrument_id == instrument_id)
            )
            return result.scalar()


class OpsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_gap(self, source: str, gap_start: datetime, gap_end: datetime) -> None:
        async with self._db.session() as s:
            s.add(
                DataGapRow(
                    source=source,
                    gap_start=gap_start,
                    gap_end=gap_end,
                    detected_at=datetime.now(UTC),
                    resolved=False,
                )
            )

    async def record_dq_check(
        self, check_date: date, check_name: str, passed: bool, details: dict[str, Any]
    ) -> None:
        stmt = pg_insert(DQCheckRow).values(
            check_date=check_date, check_name=check_name, passed=passed, details=details
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["check_date", "check_name"],
            set_={"passed": passed, "details": details},
        )
        async with self._db.session() as s:
            await s.execute(stmt)


class TokenRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, provider: str) -> AuthTokenRow | None:
        async with self._db.session() as s:
            result = await s.execute(select(AuthTokenRow).where(AuthTokenRow.provider == provider))
            return result.scalar_one_or_none()

    async def store(self, provider: str, access_token: str, expires_at: datetime | None) -> None:
        stmt = pg_insert(AuthTokenRow).values(
            provider=provider,
            access_token=access_token,
            issued_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["provider"],
            set_={
                "access_token": access_token,
                "issued_at": datetime.now(UTC),
                "expires_at": expires_at,
            },
        )
        async with self._db.session() as s:
            await s.execute(stmt)


class VolMetricsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, row: dict[str, Any]) -> None:
        stmt = pg_insert(VolMetricsDailyRow).values(**row)
        keys = {k: v for k, v in row.items() if k not in ("trade_date", "underlying")}
        stmt = stmt.on_conflict_do_update(index_elements=["trade_date", "underlying"], set_=keys)
        async with self._db.session() as s:
            await s.execute(stmt)


class FeatureRepo:
    """Feature store access. Every feature value is keyed by (name, version,
    entity, ts); recomputing with the same version overwrites idempotently."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_many(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        stmt = pg_insert(FeatureValueRow).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["feature_name", "feature_version", "entity", "ts"],
            set_={"value": stmt.excluded.value, "metadata": stmt.excluded["metadata"]},
        )
        async with self._db.session() as s:
            await s.execute(stmt)
        return len(rows)

    async def series(
        self, feature_name: str, feature_version: str, entity: str, limit: int = 400
    ) -> list[tuple[datetime, float | None]]:
        """Most recent `limit` values, returned oldest-first."""
        async with self._db.session() as s:
            result = await s.execute(
                select(FeatureValueRow.ts, FeatureValueRow.value)
                .where(
                    FeatureValueRow.feature_name == feature_name,
                    FeatureValueRow.feature_version == feature_version,
                    FeatureValueRow.entity == entity,
                )
                .order_by(FeatureValueRow.ts.desc())
                .limit(limit)
            )
            rows = result.tuples().all()
        return list(reversed(rows))


class EventsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def holidays(self) -> frozenset[date]:
        async with self._db.session() as s:
            result = await s.execute(
                select(EventRow.event_ts).where(EventRow.event_type == "HOLIDAY")
            )
            return frozenset(ts.date() for (ts,) in result.all())

    async def mark_gap_resolved(self, gap_id: int) -> None:
        async with self._db.session() as s:
            await s.execute(update(DataGapRow).where(DataGapRow.id == gap_id).values(resolved=True))
