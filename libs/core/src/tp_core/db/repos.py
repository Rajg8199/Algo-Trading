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
        # asyncpg caps bind params at 32767; this table has 11 cols/row, so the
        # full Upstox master (tens of thousands of contracts) must be chunked.
        chunk = 2000  # 11 * 2000 = 22000 params, comfortably under the cap
        async with self._db.session() as s:
            for start in range(0, len(rows), chunk):
                stmt = pg_insert(InstrumentRow).values(rows[start : start + chunk])
                stmt = stmt.on_conflict_do_update(
                    index_elements=["upstox_key"],
                    set_={"lot_size": stmt.excluded.lot_size, "is_active": stmt.excluded.is_active},
                )
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


class TradingRepo:
    """Paper-trading persistence: orders, fills, positions, daily PnL.
    Live mode will reuse these verbatim (mode column discriminates)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert_order(self, row: dict[str, Any]) -> None:
        from tp_core.db.orm import OrderRow

        async with self._db.session() as s:
            s.add(OrderRow(**row))

    async def insert_fill(self, row: dict[str, Any]) -> None:
        from tp_core.db.orm import FillRow

        async with self._db.session() as s:
            s.add(FillRow(**row))

    async def upsert_position(self, row: dict[str, Any]) -> None:
        from tp_core.db.orm import PositionRow

        stmt = pg_insert(PositionRow).values(**row)
        stmt = stmt.on_conflict_do_update(
            index_elements=["mode", "strategy", "instrument_id"],
            set_={
                "qty": row["qty"],
                "avg_price": row["avg_price"],
                "realized_pnl": row["realized_pnl"],
                "updated_at": row["updated_at"],
            },
        )
        async with self._db.session() as s:
            await s.execute(stmt)

    async def upsert_pnl_daily(self, row: dict[str, Any]) -> None:
        from tp_core.db.orm import PnlDailyRow

        stmt = pg_insert(PnlDailyRow).values(**row)
        keys = {k: v for k, v in row.items() if k not in ("trade_date", "mode", "strategy")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["trade_date", "mode", "strategy"], set_=keys
        )
        async with self._db.session() as s:
            await s.execute(stmt)

    async def open_positions(self, mode: str, strategy: str) -> list[Any]:
        from tp_core.db.orm import PositionRow

        async with self._db.session() as s:
            result = await s.execute(
                select(PositionRow).where(
                    PositionRow.mode == mode,
                    PositionRow.strategy == strategy,
                    PositionRow.qty != 0,
                )
            )
            return list(result.scalars())


class ExperimentRepo:
    """Research registry writes. trial_number is assigned here, atomically per
    hypothesis — the deflated-Sharpe denominator cannot be fudged by callers."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        run_id: Any,
        kind: str,
        hypothesis: str,
        strategy: str | None,
        params: dict[str, Any],
        data_range: tuple[date, date] | None,
        cost_multiplier: float | None,
        git_sha: str,
        metrics: dict[str, Any],
        artifacts_path: str | None = None,
        feature_set_version: str | None = None,
    ) -> int:
        from tp_core.db.orm import ExperimentRow

        async with self._db.session() as s:
            result = await s.execute(
                select(func.count())
                .select_from(ExperimentRow)
                .where(ExperimentRow.hypothesis == hypothesis)
            )
            trial_number = int(result.scalar() or 0) + 1
            s.add(
                ExperimentRow(
                    run_id=run_id,
                    kind=kind,
                    hypothesis=hypothesis,
                    strategy=strategy,
                    params=params,
                    data_range_start=data_range[0] if data_range else None,
                    data_range_end=data_range[1] if data_range else None,
                    cost_multiplier=cost_multiplier,
                    git_sha=git_sha,
                    feature_set_version=feature_set_version,
                    metrics=metrics,
                    artifacts_path=artifacts_path,
                    trial_number=trial_number,
                )
            )
        return trial_number


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

    async def latest(self, entity: str) -> tuple[dict[str, float], datetime | None]:
        """Most recent value of every feature for `entity` (DISTINCT ON name),
        plus the freshest timestamp. Empty dict if the entity has no features."""
        async with self._db.session() as s:
            result = await s.execute(
                select(FeatureValueRow.feature_name, FeatureValueRow.value, FeatureValueRow.ts)
                .where(FeatureValueRow.entity == entity)
                .order_by(FeatureValueRow.feature_name, FeatureValueRow.ts.desc())
                .distinct(FeatureValueRow.feature_name)
            )
            rows = result.all()
        values = {name: val for name, val, _ in rows if val is not None}
        latest_ts = max((ts for _, _, ts in rows), default=None)
        return values, latest_ts


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
