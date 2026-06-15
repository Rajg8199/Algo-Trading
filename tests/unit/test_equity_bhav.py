"""NSE UDiFF CM bhavcopy parser tests. A small synthetic file pins the column
mapping, the series filter, and the bad-row guards — first contact with a real
file should still go through `--probe`, but the shape is locked here."""

from __future__ import annotations

import io
import zipfile
from datetime import date

from tp_research.equity import parse_equity_bhav, probe_equity_bhav

# UDiFF CM header (subset we read) + a couple of ignored columns.
HEADER = "TradDt,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,ISIN"
CSV = "\n".join(
    [
        HEADER,
        "2026-06-12,RELIANCE,EQ,1420.0,1440.5,1410.0,1432.0,5200000,INE002A01018",
        "2026-06-12,TATAMOTORS,EQ,970.0,985.0,965.0,982.4,8100000,INE155A01022",
        "2026-06-12,SOMESME,BE,55.0,57.0,54.0,56.5,12000,INE999A01011",
        "2026-06-12,IDXJUNK,GS,100.0,101.0,99.0,100.5,0,INE000A00000",  # wrong series
        "2026-06-12,BADROW,EQ,0,0,0,0,0,INE111A01011",  # non-positive prices
    ]
)


def test_parse_keeps_equity_series_only() -> None:
    bars = parse_equity_bhav(CSV)
    symbols = {b.symbol for b in bars}
    assert symbols == {"NSE:RELIANCE", "NSE:TATAMOTORS", "NSE:SOMESME"}  # EQ + BE, not GS
    reliance = next(b for b in bars if b.symbol == "NSE:RELIANCE")
    assert reliance.day == date(2026, 6, 12)
    assert reliance.close == 1432.0
    assert reliance.volume == 5_200_000


def test_parse_skips_non_positive_rows() -> None:
    bars = parse_equity_bhav(CSV)
    assert all(b.symbol != "NSE:BADROW" for b in bars)
    assert all(min(b.open, b.high, b.low, b.close) > 0 for b in bars)


def test_parse_accepts_zip_bytes() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BhavCopy_NSE_CM_0_0_0_20260612_F_0000.csv", CSV)
    bars = parse_equity_bhav(buf.getvalue())
    assert len(bars) == 3


def test_series_filter_override() -> None:
    bars = parse_equity_bhav(CSV, series=("EQ",))  # exclude BE
    assert {b.symbol for b in bars} == {"NSE:RELIANCE", "NSE:TATAMOTORS"}


def test_probe_reports_counts() -> None:
    probe = probe_equity_bhav(CSV)
    assert probe.trade_date == date(2026, 6, 12)
    assert probe.total_rows == 5
    assert probe.equity_rows == 4  # EQ + BE rows (incl. the bad-price one)
    assert probe.parse_ok == 3  # bad-price row dropped at parse
    assert "NSE:RELIANCE" in probe.sample
