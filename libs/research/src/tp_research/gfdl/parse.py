"""Vendor file parsing, driven by a JSON mapping config — GFDL ticker and
column conventions vary by subscription, so nothing is hardcoded that the
mapping file can express. First contact with real files goes through
`--probe`, which reports match rates and unmatched samples instead of
silently dropping rows.

Default mapping (docs/data/gfdl_mapping.json) assumes the common layout:
  Ticker,Date,Time,Open,High,Low,Close,Volume,OpenInterest
  options ticker: NIFTY25JUN2424500CE   futures: NIFTY25JUN24FUT
  date: dd/mm/yyyy   time: HH:MM(:SS)   timezone: IST
"""

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

from tp_core.timeutils import IST

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    )
}


@dataclass(frozen=True)
class MappingConfig:
    option_pattern: str
    future_pattern: str
    index_tickers: dict[str, str]  # vendor ticker -> our underlying
    columns: dict[str, str]  # logical -> vendor column name
    date_format: str = "%d/%m/%Y"
    underlyings: tuple[str, ...] = ("NIFTY", "SENSEX")

    @classmethod
    def load(cls, path: Path) -> "MappingConfig":
        raw = json.loads(path.read_text())
        return cls(
            option_pattern=raw["option_pattern"],
            future_pattern=raw["future_pattern"],
            index_tickers=raw["index_tickers"],
            columns=raw["columns"],
            date_format=raw.get("date_format", "%d/%m/%Y"),
            underlyings=tuple(raw.get("underlyings", ["NIFTY", "SENSEX"])),
        )


@dataclass(frozen=True)
class ContractKey:
    underlying: str
    kind: str  # OPT | FUT | INDEX
    expiry: date | None = None
    strike: float | None = None
    option_type: str | None = None  # CE | PE
    source: str = "GFDL"  # synthetic-key namespace; bhavcopy uses NSEBHAV/BSEBHAV

    @property
    def synthetic_key(self) -> str:
        if self.kind == "INDEX":
            return f"{self.source}|{self.underlying}|INDEX"
        if self.kind == "FUT":
            return f"{self.source}|{self.underlying}|{self.expiry}|FUT"
        return f"{self.source}|{self.underlying}|{self.expiry}|{self.strike:g}|{self.option_type}"


@dataclass(frozen=True)
class Bar:
    contract: ContractKey
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    oi: int | None


@dataclass
class ParseStats:
    rows: int = 0
    parsed: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    unmatched_samples: list[str] = field(default_factory=list)

    def reject(self, reason: str, sample: str | None = None) -> None:
        self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1
        if sample and len(self.unmatched_samples) < 10:
            self.unmatched_samples.append(sample)


class TickerParser:
    def __init__(self, config: MappingConfig) -> None:
        self._config = config
        self._option_re = re.compile(config.option_pattern)
        self._future_re = re.compile(config.future_pattern)
        self._cache: dict[str, ContractKey | None] = {}

    def parse(self, ticker: str) -> ContractKey | None:
        if ticker in self._cache:
            return self._cache[ticker]
        result = self._parse_uncached(ticker.strip().upper())
        self._cache[ticker] = result
        return result

    def _expiry(self, day: str, mon: str, year: str) -> date:
        return date(2000 + int(year), MONTHS[mon], int(day))

    def _parse_uncached(self, ticker: str) -> ContractKey | None:
        if ticker in self._config.index_tickers:
            return ContractKey(self._config.index_tickers[ticker], "INDEX")
        m = self._option_re.match(ticker)
        if m:
            g = m.groupdict()
            if g["symbol"] not in self._config.underlyings:
                return None
            return ContractKey(
                underlying=g["symbol"],
                kind="OPT",
                expiry=self._expiry(g["day"], g["mon"], g["year"]),
                strike=float(g["strike"]),
                option_type=g["opt"],
            )
        m = self._future_re.match(ticker)
        if m:
            g = m.groupdict()
            if g["symbol"] not in self._config.underlyings:
                return None
            return ContractKey(
                underlying=g["symbol"],
                kind="FUT",
                expiry=self._expiry(g["day"], g["mon"], g["year"]),
            )
        return None


def parse_file(path: Path, config: MappingConfig, stats: ParseStats) -> list[Bar]:
    """Parse one vendor CSV into Bars. Bad rows are counted, never raised."""
    parser = TickerParser(config)
    cols = config.columns
    bars: list[Bar] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            stats.rows += 1
            ticker = (row.get(cols["ticker"]) or "").strip()
            contract = parser.parse(ticker)
            if contract is None:
                stats.reject("unmatched_ticker", ticker)
                continue
            try:
                d = datetime.strptime(row[cols["date"]].strip(), config.date_format).date()  # noqa: DTZ007 — date-only; tz applied at combine below
                raw_time = row[cols["time"]].strip()
                hh, mm = int(raw_time[0:2]), int(raw_time[3:5])
                ts = datetime.combine(d, time(hh, mm), tzinfo=IST)
                close = float(row[cols["close"]])
                if close <= 0:
                    stats.reject("nonpositive_close")
                    continue
                bars.append(
                    Bar(
                        contract=contract,
                        ts=ts,
                        open=float(row[cols["open"]]),
                        high=float(row[cols["high"]]),
                        low=float(row[cols["low"]]),
                        close=close,
                        volume=int(float(row[cols["volume"]])) if row.get(cols["volume"]) else None,
                        oi=int(float(row[cols["oi"]])) if row.get(cols["oi"]) else None,
                    )
                )
                stats.parsed += 1
            except (KeyError, ValueError) as exc:
                stats.reject(f"bad_row_{type(exc).__name__}")
    return bars
