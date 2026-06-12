"""FeatureContext: loads everything one (underlying, trade_date) needs once,
so feature functions stay pure and cheap.

History-dependent IV features (percentile, rank, vol-of-vol) read their own
prior values from the feature store — they become non-None automatically as
recorded history accumulates. That is by design: no backfilled fakes.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np
from sqlalchemy import text

from tp_core.db import Database
from tp_core.db.repos import FeatureRepo, InstrumentRepo
from tp_core.timeutils import IST
from tp_research.chain import ChainClose, load_chain_at_close
from tp_research.estimators import FloatArray

_DAILY_OHLC_SQL = text("""
    SELECT time_bucket('1 day', ts) AS day,
           first(ltp, ts) AS open, max(ltp) AS high,
           min(ltp) AS low, last(ltp, ts) AS close
    FROM ticks t
    JOIN instruments i USING (instrument_id)
    WHERE i.underlying = :underlying AND i.segment = 'INDEX'
      AND ts >= :start AND ts < :end
    GROUP BY day ORDER BY day
""")

_PARTICIPANT_SQL = text("""
    SELECT participant, instrument_class, long_contracts, short_contracts
    FROM participant_oi
    WHERE trade_date = (SELECT max(trade_date) FROM participant_oi
                        WHERE trade_date <= :trade_date)
""")


@dataclass
class DailyBars:
    opens: FloatArray
    highs: FloatArray
    lows: FloatArray
    closes: FloatArray

    @property
    def days(self) -> int:
        return len(self.closes)


@dataclass
class FeatureContext:
    underlying: str
    trade_date: date
    ts: datetime  # timestamp features are stamped with (close cut, IST)
    bars: DailyBars | None = None
    vix: DailyBars | None = None
    chain_front: ChainClose | None = None
    chain_next: ChainClose | None = None
    atm_iv_history: FloatArray | None = None  # prior values from feature store
    oi_total_history: FloatArray | None = None
    participant: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)


async def _load_daily_bars(
    db: Database, underlying: str, trade_date: date, lookback_days: int
) -> DailyBars | None:
    start = datetime.combine(trade_date - timedelta(days=lookback_days), time(0), tzinfo=IST)
    end = datetime.combine(trade_date + timedelta(days=1), time(0), tzinfo=IST)
    async with db.session() as s:
        result = await s.execute(
            _DAILY_OHLC_SQL, {"underlying": underlying, "start": start, "end": end}
        )
        rows = [r for r in result.all() if all(v is not None for v in r[1:])]
    if not rows:
        return None
    return DailyBars(
        opens=np.asarray([float(r.open) for r in rows]),
        highs=np.asarray([float(r.high) for r in rows]),
        lows=np.asarray([float(r.low) for r in rows]),
        closes=np.asarray([float(r.close) for r in rows]),
    )


async def build_context(db: Database, underlying: str, trade_date: date) -> FeatureContext:
    instruments = InstrumentRepo(db)
    features = FeatureRepo(db)

    ctx = FeatureContext(
        underlying=underlying,
        trade_date=trade_date,
        ts=datetime.combine(trade_date, time(15, 25), tzinfo=IST),
    )
    ctx.bars = await _load_daily_bars(db, underlying, trade_date, lookback_days=600)
    ctx.vix = await _load_daily_bars(db, "INDIAVIX", trade_date, lookback_days=600)

    expiries = await instruments.expiries(underlying, after=trade_date)
    if expiries:
        ctx.chain_front = await load_chain_at_close(db, underlying, expiries[0], trade_date)
    if len(expiries) > 1:
        ctx.chain_next = await load_chain_at_close(db, underlying, expiries[1], trade_date)

    iv_hist = await features.series("atm_iv_front", "1", underlying, limit=300)
    ctx.atm_iv_history = np.asarray([v for _, v in iv_hist if v is not None], dtype=np.float64)
    oi_hist = await features.series("oi_total_front", "1", underlying, limit=30)
    ctx.oi_total_history = np.asarray([v for _, v in oi_hist if v is not None], dtype=np.float64)

    async with db.session() as s:
        result = await s.execute(_PARTICIPANT_SQL, {"trade_date": trade_date})
        for participant, instrument_class, longs, shorts in result.all():
            ctx.participant[(participant, instrument_class)] = (longs or 0, shorts or 0)
    return ctx
