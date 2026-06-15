"""NSE UDiFF cash-market bhavcopy: download + parse to daily equity bars.

UDiFF CM is the same column family as the F&O file (FinInstrmTp, TckrSymb,
OpnPric/HghPric/LwPric/ClsPric, TtlTradgVol, ISO dates) but one row per scrip
per day. We keep only real equity series (EQ deliverable, BE trade-to-trade by
default) and skip rows with non-positive prices. Symbols are namespaced
`NSE:<ticker>` to match the TradingView/Upstox convention used elsewhere.

First contact with a real file should always go through `probe_equity_bhav`
(or the CLI `--probe`) — vendor layouts drift and nothing should be trusted
blind.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from tp_research.screener.models import DailyBar

EQUITY_BHAV_URL = (
    "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
)

# Logical field -> UDiFF CM column name.
COLUMNS = {
    "symbol": "TckrSymb",
    "series": "SctySrs",
    "date": "TradDt",
    "open": "OpnPric",
    "high": "HghPric",
    "low": "LwPric",
    "close": "ClsPric",
    "volume": "TtlTradgVol",
}
DEFAULT_SERIES = ("EQ", "BE")  # deliverable + trade-to-trade


@dataclass(frozen=True)
class EquityBhavProbe:
    trade_date: date | None
    total_rows: int
    equity_rows: int
    parse_ok: int
    sample: tuple[str, ...]  # first few symbols, for eyeballing


def _csv_text(raw: bytes | str) -> str:
    """Accept a .csv string/bytes or a zipped bhavcopy; return the CSV text."""
    if isinstance(raw, str):
        return raw
    if raw[:2] == b"PK":  # zip magic
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            name = next((n for n in zf.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                raise ValueError("no .csv inside the bhavcopy zip")
            return zf.read(name).decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _rows(raw: bytes | str) -> tuple[list[dict[str, str]], list[str]]:
    text = _csv_text(raw)
    reader = csv.DictReader(io.StringIO(text))
    fields = [f.strip() for f in (reader.fieldnames or [])]
    rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    return rows, fields


def parse_equity_bhav(
    raw: bytes | str, series: Sequence[str] = DEFAULT_SERIES
) -> list[DailyBar]:
    """Parse a UDiFF CM bhavcopy into daily equity bars, keeping only the
    requested series and skipping rows with missing/non-positive OHLC."""
    rows, _ = _rows(raw)
    keep = set(series)
    out: list[DailyBar] = []
    for row in rows:
        if row.get(COLUMNS["series"]) not in keep:
            continue
        symbol = row.get(COLUMNS["symbol"], "")
        if not symbol:
            continue
        try:
            day = datetime.strptime(row[COLUMNS["date"]], "%Y-%m-%d").date()  # noqa: DTZ007
            o = float(row[COLUMNS["open"]])
            h = float(row[COLUMNS["high"]])
            low = float(row[COLUMNS["low"]])
            c = float(row[COLUMNS["close"]])
            vol = float(row[COLUMNS["volume"]] or 0)
        except (KeyError, ValueError):
            continue
        if min(o, h, low, c) <= 0 or h < low:
            continue
        out.append(DailyBar(f"NSE:{symbol}", day, o, h, low, c, vol))
    return out


def probe_equity_bhav(raw: bytes | str, series: Sequence[str] = DEFAULT_SERIES) -> EquityBhavProbe:
    rows, _ = _rows(raw)
    bars = parse_equity_bhav(raw, series)
    trade_date = bars[0].day if bars else None
    return EquityBhavProbe(
        trade_date=trade_date,
        total_rows=len(rows),
        equity_rows=sum(1 for r in rows if r.get(COLUMNS["series"]) in set(series)),
        parse_ok=len(bars),
        sample=tuple(b.symbol for b in bars[:8]),
    )


async def download_equity_bhav(day: date) -> bytes:
    """Fetch the zipped CM bhavcopy for a date. 404 -> FileNotFoundError so the
    scheduler's hourly retry handles 'not published yet' uniformly."""
    import httpx

    url = EQUITY_BHAV_URL.format(yyyymmdd=day.strftime("%Y%m%d"))
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "application/zip,*/*",
    }
    async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
        resp = await client.get(url)
    if resp.status_code == 404:
        raise FileNotFoundError(url)
    resp.raise_for_status()
    return resp.content
