"""Snapshot dataset: replays recorded option_chain minute snapshots as
MarketState objects, oldest first, with leakage-safe features attached.

dataset_version: sha256 over (underlyings, date range, row count, min/max ts)
— stamped on every BacktestResult and experiment row. If the underlying data
changes (backfill, dedup, vendor correction), the fingerprint changes and
old results are visibly stale instead of silently irreproducible.

Feature policy: features served for trading day D are the latest computed
STRICTLY BEFORE D. Same-day features are computed at the 15:25 close cut and
serving them intraday would be lookahead.
"""

import hashlib
from collections.abc import AsyncIterator
from datetime import date, datetime, time

from sqlalchemy import text

from tp_core.db import Database
from tp_core.strategy import InstrumentMeta, MarketState, Quote
from tp_core.timeutils import IST

# Optional source filter: when :source is non-null, restrict to instruments
# whose synthetic-key namespace matches (e.g. 'NSEBHAV'), so a screen replays
# only one data origin and never mixes recorded/GFDL/bhavcopy rows. :source IS
# NULL (the default) reproduces the original unfiltered queries exactly.
_SRC = "AND (cast(:source as text) IS NULL OR split_part(i.upstox_key, '|', 1) = :source)"
_SRC_BARE = "AND (cast(:source as text) IS NULL OR split_part(upstox_key, '|', 1) = :source)"

_FINGERPRINT_SQL = text(f"""
    SELECT count(*), min(oc.ts), max(oc.ts)
    FROM option_chain oc JOIN instruments i USING (instrument_id)
    WHERE i.underlying = ANY(:unders) AND oc.ts BETWEEN :start AND :end {_SRC}
""")

_META_SQL = text(f"""
    SELECT instrument_id, underlying, segment, expiry, strike, option_type, lot_size
    FROM instruments i WHERE underlying = ANY(:unders) {_SRC_BARE}
""")

_SNAPSHOT_TIMES_SQL = text(f"""
    SELECT DISTINCT oc.ts
    FROM option_chain oc JOIN instruments i USING (instrument_id)
    WHERE i.underlying = ANY(:unders) AND oc.ts BETWEEN :start AND :end {_SRC}
    ORDER BY oc.ts
""")

_SNAPSHOT_SQL = text(f"""
    SELECT oc.instrument_id, oc.ltp, oc.bid, oc.ask, oc.iv, oc.delta, oc.oi,
           oc.spot, i.underlying
    FROM option_chain oc JOIN instruments i USING (instrument_id)
    WHERE oc.ts = :ts AND i.underlying = ANY(:unders) {_SRC}
""")

_FEATURES_BEFORE_SQL = text("""
    SELECT DISTINCT ON (entity, feature_name) entity, feature_name, value
    FROM feature_values
    WHERE ts < :before_ts AND value IS NOT NULL
    ORDER BY entity, feature_name, ts DESC
""")


def _bounds(start: date, end: date) -> dict[str, datetime]:
    return {
        "start": datetime.combine(start, time(9, 0), tzinfo=IST),
        "end": datetime.combine(end, time(16, 0), tzinfo=IST),
    }


def _float(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


async def dataset_fingerprint(
    db: Database, underlyings: list[str], start: date, end: date, source: str | None = None
) -> str:
    async with db.session() as s:
        result = await s.execute(
            _FINGERPRINT_SQL, {"unders": underlyings, "source": source, **_bounds(start, end)}
        )
        count, ts_min, ts_max = result.one()
    payload = f"{sorted(underlyings)}|{source}|{start}|{end}|{count}|{ts_min}|{ts_max}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


async def _features_before(db: Database, day: date) -> dict[str, dict[str, float]]:
    before_ts = datetime.combine(day, time(0, 0), tzinfo=IST)
    out: dict[str, dict[str, float]] = {}
    async with db.session() as s:
        rows = (await s.execute(_FEATURES_BEFORE_SQL, {"before_ts": before_ts})).all()
    for entity, name, value in rows:
        out.setdefault(entity, {})[name] = float(value)
    return out


async def replay_snapshots(
    db: Database, underlyings: list[str], start: date, end: date, source: str | None = None
) -> AsyncIterator[MarketState]:
    async with db.session() as s:
        meta_rows = (await s.execute(_META_SQL, {"unders": underlyings, "source": source})).all()
    meta = {
        r.instrument_id: InstrumentMeta(
            instrument_id=r.instrument_id,
            underlying=r.underlying,
            segment=r.segment,
            expiry=r.expiry,
            strike=_float(r.strike),
            option_type=r.option_type,
            lot_size=r.lot_size,
        )
        for r in meta_rows
    }

    async with db.session() as s:
        ts_rows = (
            await s.execute(
                _SNAPSHOT_TIMES_SQL,
                {"unders": underlyings, "source": source, **_bounds(start, end)},
            )
        ).all()
    snapshot_times: list[datetime] = [r[0] for r in ts_rows]

    current_day: date | None = None
    day_features: dict[str, dict[str, float]] = {}

    for ts in snapshot_times:
        day = ts.astimezone(IST).date()
        if day != current_day:
            current_day = day
            day_features = await _features_before(db, day)

        async with db.session() as s:
            rows = (
                await s.execute(_SNAPSHOT_SQL, {"ts": ts, "unders": underlyings, "source": source})
            ).all()

        quotes: dict[int, Quote] = {}
        spot: dict[str, float] = {}
        for r in rows:
            quotes[r.instrument_id] = Quote(
                instrument_id=r.instrument_id,
                ltp=_float(r.ltp),
                bid=_float(r.bid),
                ask=_float(r.ask),
                iv=_float(r.iv),
                delta=_float(r.delta),
                oi=_float(r.oi),
            )
            if r.spot is not None:
                spot[r.underlying] = float(r.spot)

        yield MarketState(ts=ts, spot=spot, quotes=quotes, meta=meta, features=day_features)
