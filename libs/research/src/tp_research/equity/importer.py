"""Persist equity bars and read them back as screener `DailyBar`s.

Idempotent (re-importing a day overwrites, never duplicates) and chunked
(asyncpg's 32767-bind-param cap bites on a full bhavcopy of ~2000 scrips).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tp_core.db.engine import Database
from tp_core.db.orm import EquityDailyBarRow
from tp_research.equity.bhav import DEFAULT_SERIES, parse_equity_bhav
from tp_research.screener.models import DailyBar

_CHUNK = 1000  # rows per insert: 8 cols * 1000 = 8000 binds, well under the cap


async def import_bars(db: Database, bars: list[DailyBar], source: str = "NSEBHAV") -> int:
    if not bars:
        return 0
    rows = [
        {
            "symbol": b.symbol,
            "trade_date": b.day,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": int(b.volume),
            "source": source,
        }
        for b in bars
    ]
    async with db.session() as s:
        for i in range(0, len(rows), _CHUNK):
            chunk = rows[i : i + _CHUNK]
            stmt = pg_insert(EquityDailyBarRow).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "trade_date"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "source": stmt.excluded.source,
                },
            )
            await s.execute(stmt)
    return len(rows)


async def import_bhav_file(
    db: Database, raw: bytes | str, series: tuple[str, ...] = DEFAULT_SERIES
) -> int:
    return await import_bars(db, parse_equity_bhav(raw, series))


def filter_liquid(
    bars_by_symbol: dict[str, list[DailyBar]], min_turnover_cr: float
) -> dict[str, list[DailyBar]]:
    """Keep symbols whose median daily turnover (close x volume) over the last
    ~120 days clears the floor — tradeable names only, no microcap noise."""
    floor = min_turnover_cr * 1e7  # 1 crore = 1e7 rupees
    out: dict[str, list[DailyBar]] = {}
    for sym, hist in bars_by_symbol.items():
        if len(hist) < 120:
            continue
        turn = sorted(b.close * b.volume for b in hist[-120:])
        if turn[len(turn) // 2] >= floor:
            out[sym] = hist
    return out


async def universe(db: Database, min_days: int = 220) -> list[str]:
    """Symbols with enough history to evaluate the breakout rules at all."""
    async with db.session() as s:
        result = await s.execute(
            select(EquityDailyBarRow.symbol)
            .group_by(EquityDailyBarRow.symbol)
            .having(func.count() >= min_days)
        )
        return [row[0] for row in result.all()]


async def load_recent_bars(
    db: Database,
    symbols: list[str] | None = None,
    min_date: date | None = None,
    lookback_per_symbol: int = 300,
) -> dict[str, list[DailyBar]]:
    """Return per-symbol bars, oldest-first — exactly the shape `scan` wants.
    Bounded by `lookback_per_symbol` so a long history doesn't load in full."""
    stmt = select(
        EquityDailyBarRow.symbol,
        EquityDailyBarRow.trade_date,
        EquityDailyBarRow.open,
        EquityDailyBarRow.high,
        EquityDailyBarRow.low,
        EquityDailyBarRow.close,
        EquityDailyBarRow.volume,
    )
    if symbols is not None:
        stmt = stmt.where(EquityDailyBarRow.symbol.in_(symbols))
    if min_date is not None:
        stmt = stmt.where(EquityDailyBarRow.trade_date >= min_date)
    stmt = stmt.order_by(EquityDailyBarRow.symbol, EquityDailyBarRow.trade_date)

    out: dict[str, list[DailyBar]] = {}
    async with db.session() as s:
        result = await s.execute(stmt)
        for sym, day, o, h, low, c, vol in result.all():
            out.setdefault(sym, []).append(
                DailyBar(sym, day, float(o), float(h), float(low), float(c), float(vol))
            )
    if lookback_per_symbol > 0:
        for sym in out:
            out[sym] = out[sym][-lookback_per_symbol:]
    return out
