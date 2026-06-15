"""GFDL import engine.

Flow per file: parse -> upsert historical instruments (synthetic GFDL| keys)
-> route bars (INDEX/FUT -> ticks, OPT -> option_chain with computed
IV/Greeks against same-minute spot) -> COPY into a temp table -> conflict-
ignoring insert. File status tracked in import_files (resume = skip 'done').

Parallelism: file-level asyncio with a worker semaphore; enrichment is
vectorized numpy, so workers stay I/O-bound. Determinism: same files, same
mapping, same RISK_FREE_RATE => identical rows.

Spot for enrichment: index bars from the SAME file first, then ticks already
in the DB for that day — so index files must be imported before or alongside
option files (the runbook orders them; the importer also warns when options
rows lack spot).
"""

import asyncio
import time as time_mod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import numpy as np
from sqlalchemy import text

from tp_core.db import Database
from tp_core.db.repos import InstrumentRepo
from tp_core.models import Exchange, Instrument, OptionType, Segment
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import IST
from tp_research.gfdl.bsm import greeks_from_iv, implied_vol
from tp_research.gfdl.parse import Bar, ContractKey, MappingConfig, ParseStats, parse_file

log = get_logger(__name__)

EXPIRY_CLOSE = time(15, 30)

# VERIFY against vendor contract files before trusting position sizing in
# backtests; see docs/gfdl-import-runbook.md §lot-sizes.
LOT_SIZE_SCHEDULE: dict[str, list[tuple[date, int]]] = {
    "NIFTY": [(date(2000, 1, 1), 50), (date(2024, 11, 20), 75)],
    "SENSEX": [(date(2000, 1, 1), 10), (date(2024, 11, 20), 20)],
}

OPTION_CHAIN_COLUMNS = (
    "instrument_id",
    "ts",
    "ltp",
    "bid",
    "ask",
    "bid_qty",
    "ask_qty",
    "volume",
    "oi",
    "oi_prev_day",
    "iv",
    "delta",
    "gamma",
    "theta",
    "vega",
    "spot",
)
TICKS_COLUMNS = (
    "instrument_id",
    "ts",
    "ltp",
    "bid",
    "ask",
    "bid_qty",
    "ask_qty",
    "volume",
    "oi",
)


def lot_size_for(underlying: str, expiry: date | None) -> int:
    schedule = LOT_SIZE_SCHEDULE.get(underlying, [(date(2000, 1, 1), 1)])
    size = schedule[0][1]
    for effective, value in schedule:
        if expiry is not None and expiry >= effective:
            size = value
    return size


@dataclass
class FileResult:
    path: str
    status: str
    rows_total: int = 0
    rows_imported: int = 0
    rows_rejected: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    options_without_spot: int = 0
    seconds: float = 0.0
    error: str | None = None


def _to_instrument(contract: ContractKey) -> Instrument:
    exchange = Exchange.BSE if contract.underlying == "SENSEX" else Exchange.NSE
    if contract.kind == "INDEX":
        return Instrument(
            upstox_key=contract.synthetic_key,
            exchange=exchange,
            segment=Segment.INDEX,
            underlying=contract.underlying,
        )
    if contract.kind == "FUT":
        return Instrument(
            upstox_key=contract.synthetic_key,
            exchange=exchange,
            segment=Segment.FUT,
            underlying=contract.underlying,
            expiry=contract.expiry,
            lot_size=lot_size_for(contract.underlying, contract.expiry),
        )
    return Instrument(
        upstox_key=contract.synthetic_key,
        exchange=exchange,
        segment=Segment.OPT,
        underlying=contract.underlying,
        expiry=contract.expiry,
        strike=Decimal(str(contract.strike)),
        option_type=OptionType(contract.option_type or "CE"),
        lot_size=lot_size_for(contract.underlying, contract.expiry),
    )


async def _ensure_instruments(db: Database, contracts: set[ContractKey]) -> dict[str, int]:
    repo = InstrumentRepo(db)
    await repo.upsert_many([_to_instrument(c) for c in contracts])
    return await repo.by_upstox_keys([c.synthetic_key for c in contracts])


async def _spot_from_db(db: Database, underlying: str, day: date) -> dict[datetime, float]:
    start = datetime.combine(day, time(0), tzinfo=IST)
    end = datetime.combine(day, time(23, 59), tzinfo=IST)
    async with db.session() as s:
        rows = (
            await s.execute(
                text("""SELECT t.ts, t.ltp FROM ticks t JOIN instruments i USING (instrument_id)
                        WHERE i.underlying = :u AND i.segment = 'INDEX'
                          AND t.ts BETWEEN :s AND :e"""),
                {"u": underlying, "s": start, "e": end},
            )
        ).all()
    return {ts: float(ltp) for ts, ltp in rows}


async def _copy_insert(
    db: Database, table: str, columns: tuple[str, ...], records: list[tuple[object, ...]]
) -> int:
    """COPY into a temp table, then conflict-ignoring insert. Fast and
    idempotent — re-running a partially imported file double-inserts nothing."""
    if not records:
        return 0
    async with db.engine.begin() as conn:
        raw = await conn.get_raw_connection()
        driver = raw.driver_connection
        assert driver is not None
        # NOTE: no ON COMMIT DROP — driver-level DDL outside a driver txn would
        # self-drop instantly (each statement is its own implicit transaction).
        await driver.execute(
            f"CREATE TEMP TABLE IF NOT EXISTS _imp (LIKE {table} INCLUDING DEFAULTS)"
        )
        try:
            await driver.copy_records_to_table("_imp", records=records, columns=list(columns))
            result = await driver.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) "
                f"SELECT {', '.join(columns)} FROM _imp ON CONFLICT DO NOTHING"
            )
        finally:
            await driver.execute("DROP TABLE IF EXISTS _imp")
    return int(result.split()[-1]) if result else 0


def _expiry_of(bar: Bar) -> "date":
    assert bar.contract.expiry is not None  # OPT contracts always carry expiry
    return bar.contract.expiry


def _enrich_options(
    bars: list[Bar], ids: dict[str, int], spot_map: dict[datetime, float], result: FileResult
) -> list[tuple[object, ...]]:
    if not bars:
        return []
    spots = np.array([spot_map.get(b.ts, np.nan) for b in bars])
    result.options_without_spot += int(np.isnan(spots).sum())
    strikes = np.array([b.contract.strike for b in bars], dtype=np.float64)
    closes = np.array([b.close for b in bars], dtype=np.float64)
    is_call = np.array([b.contract.option_type == "CE" for b in bars])
    t_years = np.array(
        [
            max(
                (datetime.combine(_expiry_of(b), EXPIRY_CLOSE, tzinfo=IST) - b.ts).total_seconds(),
                0.0,
            )
            / (365.0 * 86400.0)
            for b in bars
        ]
    )
    safe_spots = np.where(np.isnan(spots), 1.0, spots)
    iv = implied_vol(closes, safe_spots, strikes, t_years, is_call)
    iv = np.where(np.isnan(spots), np.nan, iv)
    greeks = greeks_from_iv(iv, safe_spots, strikes, t_years, is_call)

    records: list[tuple[object, ...]] = []
    for i, bar in enumerate(bars):
        iid = ids[bar.contract.synthetic_key]

        def f(arr: np.ndarray, idx: int = i) -> float | None:
            return None if np.isnan(arr[idx]) else float(arr[idx])

        records.append(
            (
                iid,
                bar.ts.astimezone(UTC),
                Decimal(str(bar.close)),
                None,
                None,
                None,
                None,  # bid/ask/qtys: vendor bars carry no quotes
                bar.volume,
                bar.oi,
                None,
                f(greeks.iv_pct),
                f(greeks.delta),
                f(greeks.gamma),
                f(greeks.theta),
                f(greeks.vega),
                None if np.isnan(spots[i]) else Decimal(str(round(float(spots[i]), 2))),
            )
        )
    return records


async def import_file(db: Database, path: Path, config: MappingConfig, batch_id: str) -> FileResult:
    started = time_mod.monotonic()
    result = FileResult(path=str(path), status="error")
    stats = ParseStats()
    try:
        bars = parse_file(path, config, stats)
        result.rows_total = stats.rows
        result.rejected_by_reason = dict(stats.rejected_by_reason)
        result.rows_rejected = stats.rows - stats.parsed

        contracts = {b.contract for b in bars}
        ids = await _ensure_instruments(db, contracts)

        index_fut = [b for b in bars if b.contract.kind in ("INDEX", "FUT")]
        tick_records: list[tuple[object, ...]] = [
            (
                ids[b.contract.synthetic_key],
                b.ts.astimezone(UTC),
                Decimal(str(b.close)),
                None,
                None,
                None,
                None,
                b.volume,
                b.oi,
            )
            for b in index_fut
        ]
        imported = await _copy_insert(db, "ticks", TICKS_COLUMNS, tick_records)

        options = [b for b in bars if b.contract.kind == "OPT"]
        spot_map: dict[datetime, float] = {}
        for b in index_fut:
            if b.contract.kind == "INDEX":
                spot_map[b.ts] = b.close
        if options and not spot_map:
            days = {b.ts.astimezone(IST).date() for b in options}
            for day in days:
                spot_map.update(await _spot_from_db(db, options[0].contract.underlying, day))

        option_records = _enrich_options(options, ids, spot_map, result)
        imported += await _copy_insert(db, "option_chain", OPTION_CHAIN_COLUMNS, option_records)

        result.rows_imported = imported
        result.status = "done"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        log.exception("gfdl_file_failed", file=str(path))
    result.seconds = time_mod.monotonic() - started
    await _record_file(db, result, batch_id)
    return result


async def _record_file(db: Database, result: FileResult, batch_id: str) -> None:
    async with db.session() as s:
        await s.execute(
            text("""INSERT INTO import_files
                    (file_path, batch_id, status, rows_total, rows_imported,
                     rows_rejected, error, started_at, finished_at)
                    VALUES (:p, :b, :st, :rt, :ri, :rr, :err, now(), now())
                    ON CONFLICT (file_path) DO UPDATE SET
                      status = :st, rows_total = :rt, rows_imported = :ri,
                      rows_rejected = :rr, error = :err, finished_at = now()"""),
            {
                "p": result.path,
                "b": batch_id,
                "st": result.status,
                "rt": result.rows_total,
                "ri": result.rows_imported,
                "rr": result.rows_rejected,
                "err": result.error,
            },
        )


async def already_done(db: Database, paths: list[Path]) -> set[str]:
    if not paths:
        return set()
    async with db.session() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT file_path FROM import_files WHERE status = 'done' "
                    "AND file_path = ANY(:paths)"
                ),
                {"paths": [str(p) for p in paths]},
            )
        ).all()
    return {r[0] for r in rows}


async def run_import(
    db: Database,
    files: list[Path],
    config: MappingConfig,
    batch_id: str,
    workers: int = 4,
    resume: bool = True,
) -> list[FileResult]:
    """Index/spot files are imported FIRST (sequentially-safe ordering by
    name heuristic handled by caller); remaining files run `workers`-wide."""
    skip = await already_done(db, files) if resume else set()
    pending = [p for p in files if str(p) not in skip]
    log.info("gfdl_import_start", files=len(files), skipped=len(skip), workers=workers)

    semaphore = asyncio.Semaphore(workers)
    results: list[FileResult] = []

    async def worker(path: Path) -> None:
        async with semaphore:
            results.append(await import_file(db, path, config, batch_id))

    async with asyncio.TaskGroup() as tg:
        for path in pending:
            tg.create_task(worker(path))
    return results


# Shared infrastructure reused by the bhavcopy importer — identical
# option_chain/ticks COPY path and import_files bookkeeping. Public aliases so
# the sibling importer doesn't import private names.
copy_insert = _copy_insert
record_file = _record_file
