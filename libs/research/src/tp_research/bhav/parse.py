"""EOD F&O bhavcopy parsing, driven by a JSON mapping config — exactly the
GFDL philosophy (vendor layouts vary; nothing hardcoded the mapping can
express; first contact goes through `--probe`). Unlike GFDL 1-min bars,
bhavcopy is ONE row per contract per trading day and carries, in-row:

  - the official SETTLEMENT price (the canonical EOD mark for IV),
  - the UNDERLYING price (spot — no separate index file needed),
  - the board LOT size (authoritative — no hardcoded schedule needed).

Default mapping (docs/data/bhav_mapping.json) targets NSE's UDiFF F&O bhavcopy
(the standard since 2024-07): index options = FinInstrmTp 'IDO', index futures
= 'IDF'; ISO dates. BSE SENSEX uses a different layout — point a separate
mapping at it and probe first. NSE ships the file zipped; .zip and .csv both
work.
"""

import csv
import io
import json
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

from tp_core.timeutils import IST
from tp_research.gfdl.parse import ContractKey

SETTLEMENT_TIME = time(15, 30)  # EOD snapshot timestamp (market close, IST)


@dataclass(frozen=True)
class BhavMappingConfig:
    columns: dict[str, str]  # logical -> vendor column name
    index_option_types: tuple[str, ...]  # FinInstrmTp values that are index options
    index_future_types: tuple[str, ...]  # FinInstrmTp values that are index futures
    call_value: str  # OptnTp value meaning a call
    put_value: str  # OptnTp value meaning a put
    source_tag: str = "NSEBHAV"  # synthetic-key namespace
    date_format: str = "%Y-%m-%d"
    underlyings: tuple[str, ...] = ("NIFTY", "SENSEX")

    @classmethod
    def load(cls, path: Path) -> "BhavMappingConfig":
        raw = json.loads(path.read_text())
        return cls(
            columns=raw["columns"],
            index_option_types=tuple(raw["index_option_types"]),
            index_future_types=tuple(raw["index_future_types"]),
            call_value=raw["option_type_values"]["call"],
            put_value=raw["option_type_values"]["put"],
            source_tag=raw.get("source_tag", "NSEBHAV"),
            date_format=raw.get("date_format", "%Y-%m-%d"),
            underlyings=tuple(raw.get("underlyings", ["NIFTY", "SENSEX"])),
        )


@dataclass(frozen=True)
class BhavBar:
    """One contract on one trading day. `close` is the day's last traded
    price; `settlement` is the official settlement (used as the mark).
    open/high/low are the day's OHLC — carried for futures so the index
    realized-vol series gets a true daily range (settlement files have no
    intraday spot H/L; the near-month future is the standard proxy)."""

    contract: ContractKey
    ts: datetime
    close: float
    settlement: float
    underlying_price: float | None
    volume: int | None
    oi: int | None
    oi_prev_day: int | None
    lot_size: int | None
    open: float | None = None
    high: float | None = None
    low: float | None = None


@dataclass
class BhavStats:
    rows: int = 0  # total file rows seen
    selected: int = 0  # in-universe rows (our instrument types + underlyings)
    parsed: int = 0  # successfully parsed bars
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    unmatched_samples: list[str] = field(default_factory=list)

    def reject(self, reason: str, sample: str | None = None) -> None:
        self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1
        if sample and len(self.unmatched_samples) < 10:
            self.unmatched_samples.append(sample)


def _f(value: str | None) -> float | None:
    if value is None:
        return None
    v = value.strip()
    if v in ("", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _i(value: str | None) -> int | None:
    f = _f(value)
    return None if f is None else int(f)


def _iter_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield CSV rows from a .csv or a zipped bhavcopy (.zip / .csv.zip)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                return
            with z.open(name) as raw:
                yield from csv.DictReader(io.TextIOWrapper(raw, "utf-8"))
    else:
        with path.open() as f:
            yield from csv.DictReader(f)


def parse_file(path: Path, config: BhavMappingConfig, stats: BhavStats) -> list[BhavBar]:
    """Parse one bhavcopy into BhavBars. Out-of-universe rows (stock options,
    other indices) are skipped silently — only in-universe rows count toward
    rows/parsed, so the probe's parse-rate reflects OUR contracts, not the
    thousands of stock-option rows the file also contains."""
    cols = config.columns
    bars: list[BhavBar] = []
    for row in _iter_rows(path):
        stats.rows += 1
        itype = (row.get(cols["instrument_type"]) or "").strip().upper()
        symbol = (row.get(cols["symbol"]) or "").strip().upper()
        is_option = itype in config.index_option_types
        is_future = itype in config.index_future_types
        if not (is_option or is_future) or symbol not in config.underlyings:
            continue
        stats.selected += 1
        try:
            trade_day = datetime.strptime(  # noqa: DTZ007 — date-only; tz applied at combine
                row[cols["trade_date"]].strip(), config.date_format
            ).date()
            ts = datetime.combine(trade_day, SETTLEMENT_TIME, tzinfo=IST)
            settlement = float(row[cols["settlement"]])
            if settlement <= 0:
                stats.reject("nonpositive_settlement")
                continue
            close_raw = _f(row.get(cols["close"]))
            close = close_raw if close_raw and close_raw > 0 else settlement
            expiry = datetime.strptime(  # noqa: DTZ007 — date-only
                row[cols["expiry"]].strip(), config.date_format
            ).date()

            if is_option:
                strike = float(row[cols["strike"]])
                if strike <= 0:
                    stats.reject("nonpositive_strike")
                    continue
                otype_raw = (row.get(cols["option_type"]) or "").strip().upper()
                if otype_raw == config.call_value:
                    otype = "CE"
                elif otype_raw == config.put_value:
                    otype = "PE"
                else:
                    stats.reject("bad_option_type", otype_raw)
                    continue
                contract = ContractKey(
                    underlying=symbol,
                    kind="OPT",
                    expiry=expiry,
                    strike=strike,
                    option_type=otype,
                    source=config.source_tag,
                )
            else:
                contract = ContractKey(
                    underlying=symbol, kind="FUT", expiry=expiry, source=config.source_tag
                )

            underlying_price = _f(row.get(cols["underlying_price"]))
            if underlying_price is not None and underlying_price <= 0:
                underlying_price = None
            oi = _i(row.get(cols["oi"]))
            change_col = cols.get("change_in_oi")
            change_oi = _i(row.get(change_col)) if change_col else None
            oi_prev = oi - change_oi if (oi is not None and change_oi is not None) else None
            lot_col = cols.get("lot_size")
            lot_size = _i(row.get(lot_col)) if lot_col else None

            bars.append(
                BhavBar(
                    contract=contract,
                    ts=ts,
                    close=close,
                    settlement=settlement,
                    underlying_price=underlying_price,
                    volume=_i(row.get(cols["volume"])),
                    oi=oi,
                    oi_prev_day=oi_prev,
                    lot_size=lot_size,
                    open=_f(row.get(cols["open"])),
                    high=_f(row.get(cols["high"])),
                    low=_f(row.get(cols["low"])),
                )
            )
            stats.parsed += 1
        except (KeyError, ValueError) as exc:
            stats.reject(f"bad_row_{type(exc).__name__}")
    return bars


def synthesize_index_ohlc(bars: list[BhavBar], config: BhavMappingConfig) -> list[BhavBar]:
    """Derive one daily INDEX bar per (underlying, day) carrying a true O/H/L/C
    range, so realized-vol features (Parkinson/Yang-Zhang/HAR) work. An F&O
    bhavcopy has no cash-index row and no intraday spot H/L, so the near-month
    INDEX FUTURE's OHLC is used (its range tracks the index; basis ~cancels in
    range/return-based RV). Falls back to a flat bar at the underlying close
    when no future is present for that day."""
    futures: dict[tuple[str, date], BhavBar] = {}
    flat_close: dict[tuple[str, date], float] = {}
    for b in bars:
        key = (b.contract.underlying, b.ts.astimezone(IST).date())
        if b.contract.kind == "FUT" and b.contract.expiry is not None:
            cur = futures.get(key)
            if cur is None or (
                cur.contract.expiry is not None and b.contract.expiry < cur.contract.expiry
            ):
                futures[key] = b  # nearest expiry
        if b.underlying_price is not None:
            flat_close[key] = b.underlying_price

    out: list[BhavBar] = []
    for key in {*futures, *flat_close}:
        underlying, _ = key
        fut = futures.get(key)
        index_key = ContractKey(underlying=underlying, kind="INDEX", source=config.source_tag)
        if fut is not None and None not in (fut.open, fut.high, fut.low):
            out.append(
                BhavBar(
                    contract=index_key,
                    ts=fut.ts,
                    close=fut.close,
                    settlement=fut.close,
                    underlying_price=fut.close,
                    volume=None,
                    oi=None,
                    oi_prev_day=None,
                    lot_size=None,
                    open=fut.open,
                    high=fut.high,
                    low=fut.low,
                )
            )
        elif key in flat_close:
            close = flat_close[key]
            ts = fut.ts if fut else next(b.ts for b in bars if b.underlying_price == close)
            out.append(
                BhavBar(
                    contract=index_key,
                    ts=ts,
                    close=close,
                    settlement=close,
                    underlying_price=close,
                    volume=None,
                    oi=None,
                    oi_prev_day=None,
                    lot_size=None,
                    open=close,
                    high=close,
                    low=close,
                )
            )
    return out
