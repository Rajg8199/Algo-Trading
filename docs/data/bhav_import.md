# NSE/BSE EOD bhavcopy import — free historical option data

The only *free* source of historical NIFTY/SENSEX option data. EOD settlement
prices + OI per strike, going back years. No intraday, no bid/ask — this backs
**EXP-001-EOD** (a screen), not the intraday Experiment 001. See
`docs/research/vrp-experiment-001-eod.md`.

## Where to get the files (free)

- **NSE (NIFTY):** https://www.nseindia.com/all-reports → Derivatives →
  *"F&O - UDiFF Common Bhavcopy Final (zip)"*. Historical archive:
  `https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip`.
  NSE blocks naive scrapers — set a browser `User-Agent` and hit the homepage
  first for cookies, or download by hand. One zip per trading day.
- **BSE (SENSEX):** https://www.bseindia.com/ derivatives EOD reports.
  **Different layout** — do not assume the NSE columns. Make a second mapping
  file with `source_tag: "BSEBHAV"` and `--probe` it before any import.

Drop the files (zipped is fine) under one directory, e.g. `/data/bhav/`.

## Workflow

The pipeline is mapping-driven and probe-first, exactly like GFDL. Never run a
full import before a clean probe.

```bash
# 1. PROBE a real file first — verifies the mapping matches NSE's actual columns.
#    Want: selected > 0, parse rate > 95%, sane first-option line (settle/spot/lot).
uv run python scripts/bhav_import.py --probe /data/bhav/BhavCopy_NSE_FO_0_0_0_20260612_F_0000.csv.zip

# 2. FULL IMPORT (no ordering needed — spot is in-row). Resumable + idempotent.
uv run python scripts/bhav_import.py --root /data/bhav --glob "**/*.csv*" \
    --batch 2026-06-bhav --workers 4

# 3. EXP-001-EOD READINESS — PASS/FAIL per preflight criterion (NIFTY).
uv run python scripts/bhav_import.py --readiness 2021-01-01:2026-06-01
```

If the probe shows `selected=0` or unmatched samples, fix
`docs/data/bhav_mapping.json` (vendor column names / instrument-type codes)
and re-probe. Nothing is hardcoded that the mapping can express.

## What the importer does

- Routes index **options** (`FinInstrmTp=IDO`) → `option_chain`, with IV/Greeks
  computed Black-Scholes from **settlement** vs the in-row **underlying price**.
- Routes index **futures** (`IDF`) → `ticks`; synthesizes one daily **INDEX
  spot** tick per underlying from `UndrlygPric` so realized-vol features get a
  spot series for free.
- Takes **lot size from the file** (`NewBrdLotQty`) — authoritative, so this
  also resolves the previously-unverified lot-size schedule.
- Synthetic instrument keys are namespaced `NSEBHAV|…` / `BSEBHAV|…`, kept
  distinct from GFDL's `GFDL|…` keys; readiness queries filter to bhavcopy
  sources only (never mixes data origins).

## Blockers (must clear before EXP-001-EOD runs)

1. `eod_granularity_blocker` in the readiness report is **FAILED by design**.
   Flip it manually only after the `tp_backtest` EOD execution adapter exists
   and `synthetic_spread_pct` is calibrated from recorded spreads.
2. SENSEX needs the BSE mapping (above). NIFTY (NSE) works with the shipped
   `bhav_mapping.json` once probed.
