"""EOD bhavcopy import engine.

Per file: parse -> synthesize daily INDEX spot bars -> upsert historical
instruments (synthetic NSEBHAV|/BSEBHAV| keys, lot size taken from the file)
-> route INDEX/FUT -> ticks, OPT -> option_chain with IV/Greeks computed from
the SETTLEMENT price vs the in-row underlying price (tp_research.gfdl.bsm) ->
COPY + conflict-ignoring insert. Idempotent and resumable, exactly like the
GFDL importer whose COPY/bookkeeping helpers this reuses.

EOD GRANULARITY — this data has one snapshot per contract per day and no
bid/ask. It backs the EXP-001-EOD variant (daily entry/exit at settlement ±
modeled slippage), never the intraday Experiment 001.
"""

import asyncio
import time as time_mod
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from tp_core.db import Database
from tp_core.db.repos import InstrumentRepo
from tp_core.models import Exchange, Instrument, OptionType, Segment
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import IST
from tp_research.bhav.parse import (
    BhavBar,
    BhavMappingConfig,
    BhavStats,
    parse_file,
    synthesize_index_ohlc,
)
from tp_research.gfdl.bsm import greeks_from_iv, implied_vol
from tp_research.gfdl.importer import (
    EXPIRY_CLOSE,
    OPTION_CHAIN_COLUMNS,
    TICKS_COLUMNS,
    FileResult,
    already_done,
    copy_insert,
    lot_size_for,
    record_file,
)
from tp_research.gfdl.parse import ContractKey

log = get_logger(__name__)


@dataclass
class BhavFileResult(FileResult):
    selected: int = 0  # in-universe rows considered (excludes stock options etc.)


def _to_instrument(contract: ContractKey, lot: int | None) -> Instrument:
    exchange = Exchange.BSE if contract.underlying == "SENSEX" else Exchange.NSE
    if contract.kind == "INDEX":
        return Instrument(
            upstox_key=contract.synthetic_key,
            exchange=exchange,
            segment=Segment.INDEX,
            underlying=contract.underlying,
        )
    size = lot if lot else lot_size_for(contract.underlying, contract.expiry)
    if contract.kind == "FUT":
        return Instrument(
            upstox_key=contract.synthetic_key,
            exchange=exchange,
            segment=Segment.FUT,
            underlying=contract.underlying,
            expiry=contract.expiry,
            lot_size=size,
        )
    return Instrument(
        upstox_key=contract.synthetic_key,
        exchange=exchange,
        segment=Segment.OPT,
        underlying=contract.underlying,
        expiry=contract.expiry,
        strike=Decimal(str(contract.strike)),
        option_type=OptionType(contract.option_type or "CE"),
        lot_size=size,
    )


async def _ensure_instruments(
    db: Database, contracts: set[ContractKey], lot_by_key: dict[str, int]
) -> dict[str, int]:
    repo = InstrumentRepo(db)
    await repo.upsert_many([_to_instrument(c, lot_by_key.get(c.synthetic_key)) for c in contracts])
    return await repo.by_upstox_keys([c.synthetic_key for c in contracts])


def _enrich_options(
    bars: list[BhavBar], ids: dict[str, int], result: BhavFileResult
) -> list[tuple[object, ...]]:
    if not bars:
        return []
    spots = np.array(
        [b.underlying_price if b.underlying_price is not None else np.nan for b in bars]
    )
    result.options_without_spot += int(np.isnan(spots).sum())
    strikes = np.array([b.contract.strike for b in bars], dtype=np.float64)
    settle = np.array([b.settlement for b in bars], dtype=np.float64)
    is_call: NDArray[np.bool_] = np.array([b.contract.option_type == "CE" for b in bars])
    assert all(b.contract.expiry is not None for b in bars)  # OPT bars always carry expiry
    t_years = np.array(
        [
            max(
                (
                    datetime.combine(b.contract.expiry, EXPIRY_CLOSE, tzinfo=IST) - b.ts  # type: ignore[arg-type]
                ).total_seconds(),
                0.0,
            )
            / (365.0 * 86400.0)
            for b in bars
        ]
    )
    safe_spots = np.where(np.isnan(spots), 1.0, spots)
    iv = implied_vol(settle, safe_spots, strikes, t_years, is_call)
    iv = np.where(np.isnan(spots), np.nan, iv)
    greeks = greeks_from_iv(iv, safe_spots, strikes, t_years, is_call)

    records: list[tuple[object, ...]] = []
    for i, bar in enumerate(bars):
        iid = ids[bar.contract.synthetic_key]

        def f(arr: NDArray[np.float64], idx: int = i) -> float | None:
            return None if np.isnan(arr[idx]) else float(arr[idx])

        records.append(
            (
                iid,
                bar.ts.astimezone(UTC),
                Decimal(str(bar.settlement)),  # settlement is the EOD mark
                None,
                None,
                None,
                None,  # bid/ask/qtys: bhavcopy carries no quotes
                bar.volume,
                bar.oi,
                bar.oi_prev_day,
                f(greeks.iv_pct),
                f(greeks.delta),
                f(greeks.gamma),
                f(greeks.theta),
                f(greeks.vega),
                None if np.isnan(spots[i]) else Decimal(str(round(float(spots[i]), 2))),
            )
        )
    return records


def _tick_records(bars: list[BhavBar], ids: dict[str, int]) -> list[tuple[object, ...]]:
    return [
        (
            ids[b.contract.synthetic_key],
            b.ts.astimezone(UTC),
            Decimal(str(b.settlement)),
            None,
            None,
            None,
            None,
            b.volume,
            b.oi,
        )
        for b in bars
    ]


# O/H/L/C stamped at distinct intraday times so a 1-day time_bucket recovers
# first()=open, last()=close, max()=high, min()=low for the daily-bars query.
_INDEX_OHLC_TIMES = (time(9, 15), time(9, 16), time(9, 17), time(15, 30))


def _index_tick_records(bars: list[BhavBar], ids: dict[str, int]) -> list[tuple[object, ...]]:
    records: list[tuple[object, ...]] = []
    for b in bars:
        iid = ids[b.contract.synthetic_key]
        day = b.ts.astimezone(IST).date()
        for t, px in zip(_INDEX_OHLC_TIMES, (b.open, b.high, b.low, b.close), strict=True):
            if px is None:
                continue
            ts = datetime.combine(day, t, tzinfo=IST).astimezone(UTC)
            records.append((iid, ts, Decimal(str(px)), None, None, None, None, None, None))
    return records


async def import_file(
    db: Database, path: Path, config: BhavMappingConfig, batch_id: str
) -> BhavFileResult:
    started = time_mod.monotonic()
    result = BhavFileResult(path=str(path), status="error")
    stats = BhavStats()
    try:
        bars = parse_file(path, config, stats)
        index_bars = synthesize_index_ohlc(bars, config)
        result.selected = stats.selected
        result.rows_total = stats.selected
        result.rejected_by_reason = dict(stats.rejected_by_reason)
        result.rows_rejected = stats.selected - stats.parsed

        lot_by_key: dict[str, int] = {}
        for b in bars:
            if b.lot_size:
                key = b.contract.synthetic_key
                lot_by_key[key] = max(lot_by_key.get(key, 0), b.lot_size)
        contracts = {b.contract for b in bars} | {b.contract for b in index_bars}
        ids = await _ensure_instruments(db, contracts, lot_by_key)

        fut_bars = [b for b in bars if b.contract.kind == "FUT"]
        tick_records = _index_tick_records(index_bars, ids) + _tick_records(fut_bars, ids)
        imported = await copy_insert(db, "ticks", TICKS_COLUMNS, tick_records)

        options = [b for b in bars if b.contract.kind == "OPT"]
        option_records = _enrich_options(options, ids, result)
        imported += await copy_insert(db, "option_chain", OPTION_CHAIN_COLUMNS, option_records)

        result.rows_imported = imported
        result.status = "done"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        log.exception("bhav_file_failed", file=str(path))
    result.seconds = time_mod.monotonic() - started
    await record_file(db, result, batch_id)
    return result


async def run_import(
    db: Database,
    files: list[Path],
    config: BhavMappingConfig,
    batch_id: str,
    workers: int = 4,
    resume: bool = True,
) -> list[BhavFileResult]:
    """No index-ordering needed (spot is in-row); all files run workers-wide."""
    skip = await already_done(db, files) if resume else set()
    pending = [p for p in files if str(p) not in skip]
    log.info("bhav_import_start", files=len(files), skipped=len(skip), workers=workers)

    semaphore = asyncio.Semaphore(workers)
    results: list[BhavFileResult] = []

    async def worker(path: Path) -> None:
        async with semaphore:
            results.append(await import_file(db, path, config, batch_id))

    async with asyncio.TaskGroup() as tg:
        for path in pending:
            tg.create_task(worker(path))
    return results
