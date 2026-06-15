from pathlib import Path

import numpy as np
from tp_research.bhav.importer import BhavFileResult, _enrich_options
from tp_research.bhav.parse import BhavMappingConfig, BhavStats, parse_file, synthesize_index_ohlc
from tp_research.gfdl.bsm import bs_price
from tp_research.gfdl.importer import OPTION_CHAIN_COLUMNS

MAPPING = BhavMappingConfig.load(Path("docs/data/bhav_mapping.json"))

HEADER = (
    "TradDt,FinInstrmTp,TckrSymb,XpryDt,StrkPric,OptnTp,OpnPric,HghPric,LwPric,"
    "ClsPric,SttlmPric,UndrlygPric,TtlTradgVol,OpnIntrst,ChngInOpnIntrst,NewBrdLotQty\n"
)

# A NIFTY ATM call priced at a known vol, so enrichment must recover it.
_T = 5.0 / 365.0
_TRUE_VOL = 0.14
_CALL_SETTLE = float(
    bs_price(
        np.array([24500.0]),
        np.array([24500.0]),
        np.array([_T]),
        np.array([_TRUE_VOL]),
        np.array([True]),
    )[0]
)


def _write_sample(tmp_path: Path) -> Path:
    f = tmp_path / "BhavCopy_NSE_FO_0_0_0_20260612_F_0000.csv"
    f.write_text(
        HEADER
        # in-universe NIFTY index option (priced at 14% vol)
        + f"2026-06-12,IDO,NIFTY,2026-06-17,24500,CE,200,210,190,{_CALL_SETTLE:.4f},"
        f"{_CALL_SETTLE:.4f},24500,1200000,50000,1000,75\n"
        # in-universe NIFTY index future
         + "2026-06-12,IDF,NIFTY,2026-06-25,-,-,24560,24600,24500,24550,24550,24500,"
        "900000,200000,500,75\n"
        # stock option — filtered (not an index instrument type)
        + "2026-06-12,STO,RELIANCE,2026-06-25,2900,CE,30,32,28,31,31,2895,5000,1000,10,250\n"
        # other index — filtered (underlying out of universe)
        + "2026-06-12,IDO,BANKNIFTY,2026-06-17,52000,CE,300,310,290,305,305,52000,7000,8000,1,35\n"
        # in-universe but bad settlement — rejected
        + "2026-06-12,IDO,NIFTY,2026-06-17,25000,PE,5,6,4,0,0,24500,100,1000,10,75\n"
    )
    return f


def test_parse_selects_universe_and_counts_rejects(tmp_path: Path) -> None:
    stats = BhavStats()
    bars = parse_file(_write_sample(tmp_path), MAPPING, stats)
    assert stats.rows == 5
    assert stats.selected == 3  # 2 NIFTY options + 1 NIFTY future (stock/banknifty skipped)
    assert stats.parsed == 2
    assert stats.rejected_by_reason["nonpositive_settlement"] == 1
    assert {b.contract.kind for b in bars} == {"OPT", "FUT"}


def test_in_row_fields_extracted(tmp_path: Path) -> None:
    stats = BhavStats()
    bars = parse_file(_write_sample(tmp_path), MAPPING, stats)
    opt = next(b for b in bars if b.contract.kind == "OPT")
    assert opt.contract.synthetic_key.startswith("NSEBHAV|NIFTY|")
    assert opt.lot_size == 75  # lot size comes from the file, not a hardcoded schedule
    assert opt.underlying_price == 24500.0  # spot is in-row
    assert opt.oi_prev_day == 49000  # oi (50000) - change_in_oi (1000)

    fut = next(b for b in bars if b.contract.kind == "FUT")
    assert fut.contract.strike is None and fut.contract.option_type is None


def test_synthesize_index_ohlc_from_near_month_future(tmp_path: Path) -> None:
    stats = BhavStats()
    bars = parse_file(_write_sample(tmp_path), MAPPING, stats)
    index_bars = synthesize_index_ohlc(bars, MAPPING)
    assert len(index_bars) == 1  # one (NIFTY, 2026-06-12) bar from the near-month future
    idx = index_bars[0]
    assert idx.contract.kind == "INDEX"
    # OHLC taken from the IDF future row (open 24560, high 24600, low 24500, close 24550)
    assert (idx.open, idx.high, idx.low, idx.close) == (24560.0, 24600.0, 24500.0, 24550.0)
    assert idx.high > idx.low  # a real range, not a flat bar


def test_enrichment_recovers_known_iv(tmp_path: Path) -> None:
    stats = BhavStats()
    bars = parse_file(_write_sample(tmp_path), MAPPING, stats)
    options = [b for b in bars if b.contract.kind == "OPT"]
    ids = {b.contract.synthetic_key: i for i, b in enumerate(options)}
    result = BhavFileResult(path="t", status="x")
    records = _enrich_options(options, ids, result)

    iv_idx = OPTION_CHAIN_COLUMNS.index("iv")
    spot_idx = OPTION_CHAIN_COLUMNS.index("spot")
    iv_pct = records[0][iv_idx]
    assert iv_pct is not None
    assert abs(float(iv_pct) - 14.0) < 0.1  # recovered the 14% vol from settlement vs spot
    assert float(records[0][spot_idx]) == 24500.0
    assert result.options_without_spot == 0
