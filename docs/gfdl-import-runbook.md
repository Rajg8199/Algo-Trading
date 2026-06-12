# GFDL IMPORT RUNBOOK

From vendor delivery to "ready for Experiment 001". Single engineer, ~half a
day of attended work for a 3-year import (most of it waiting).

## Architecture (one paragraph)

`scripts/gfdl_import.py` → `tp_research.gfdl`: mapping-config-driven parser
(`parse.py`) → historical-instrument upsert (synthetic `GFDL|…` keys, expired
contracts included) → INDEX/FUT bars into `ticks`, OPT bars into
`option_chain` with **computed** Black-Scholes IV/Greeks against same-minute
spot (`bsm.py`, vectorized bisection, r=6.5%) → COPY into temp table →
conflict-ignoring insert (idempotent, hence resumable) → per-file state in
`import_files` → batch report + Experiment-001 readiness report (`report.py`).
Parallelism: `--workers N` file-level async.

## Schema mapping

`docs/data/gfdl_mapping.json` owns everything vendor-specific: ticker regexes
(named groups `symbol/day/mon/year/strike/opt`), index ticker aliases, column
names, date format. **Nothing else in the pipeline knows GFDL conventions.**
If the vendor layout differs, you edit the JSON, not the code.

Target mapping: option bars → `option_chain` (ltp=close, oi, volume, computed
iv/delta/gamma/theta/vega, spot; **bid/ask stay NULL — vendor bars carry no
quotes and we never fabricate data**); index/futures bars → `ticks`.

## Step-by-step

1. **Receive files**, place under e.g. `/data/gfdl/` (any layout; `--glob`).
2. **Probe FIRST — always:**
   `uv run python scripts/gfdl_import.py --probe /data/gfdl/<one-file>.csv`
   Success: parse rate >95%, kinds counted, zero unmatched samples. Anything
   else: fix `gfdl_mapping.json` patterns using the printed samples; re-probe.
3. **Migrate:** `uv run alembic upgrade head` (adds `import_files`, rev 0002).
4. **Dry-run one day:** import a single day's files into the real DB
   (`--root /data/gfdl/2023-06-01 --batch probe-day`), then sanity-query:
   IV near-ATM should look like real vol (10–25 for NIFTY), deltas signed
   correctly, spot joined >95%. Wrong-looking IV = wrong spot join or wrong
   expiry parse — stop and diagnose.
5. **Full import:**
   `uv run python scripts/gfdl_import.py --root /data/gfdl --glob "**/*.csv" --batch gfdl-3yr --workers 4`
   Index files auto-sort first (spot must precede option enrichment). Crash
   or Ctrl-C anytime: re-run the same command — `done` files skip, partial
   files re-import idempotently.
6. **Read the report:** `datalake/imports/gfdl-3yr/report.json` — rows
   imported/rejected by reason, options_without_spot (investigate if >1%),
   throughput benchmark (synthetic-data baseline: ~4k rows/s at trivial batch
   sizes; expect 50–150k rows/s on real multi-MB files — record the actual
   number here after the first real batch).
7. **DQ over imported history:** run the validation framework on sampled days
   (`uv run python -c` loop over `tp_research.validation.run_validation`) or
   simply run `scripts/burnin_check.py --date <day>` for ~10 spread-out days.
8. **Feature backfill:** loop `run_feature_engine` over the imported range
   (oldest → newest, so history-dependent features see their lookbacks).
9. **Readiness verdict:**
   `uv run python scripts/gfdl_import.py --readiness 2023-06-01:2026-06-01`
   Writes `datalake/imports/readiness.json` with PASS/FAIL per criterion.

## Lot sizes (VERIFY before any backtest)

`LOT_SIZE_SCHEDULE` in `importer.py` encodes best-known values (NIFTY 50→75
and SENSEX 10→20 at the Nov-2024 revision) — **verify against the vendor's
contract file / NSE circulars for the full range and amend the schedule**;
position sizing in backtests multiplies through it.

## Known limitations (by design, stated honestly)

- **No bid/ask** in vendor bars → the readiness report contains a permanent
  `synthetic_spread_blocker` FAIL until you calibrate
  `BacktestConfig.synthetic_spread_pct` from our own recorded spreads
  (registered amendment; the fill model only uses it when real quotes are
  absent, and recorded data is never affected).
- **IV/Greeks are computed, not observed** (BS, r=6.5%, q=0). Reconcile a
  sample against recorded vendor IV once both exist (R-1).
- 1-min bars ≠ quotes: `ltp` is a bar close; intrabar sequencing is gone.
  Fine for the registered VRP design (minute-cadence decisions); not fine for
  sub-minute strategies — don't use this data for those.

## Failure handling

| Symptom | Action |
|---|---|
| File status `error` in `import_files` | error text stored in the row; fix cause, re-run (resume retries non-done files) |
| High `unmatched_ticker` | mapping regex; probe the file, patch JSON |
| High `options_without_spot` | index file for that day missing/late — import it, then re-run options file with `--no-resume` for that file's batch |
| IV mostly NaN on a day | spot join broken (check ticks for that day) or expiry parse wrong (strike/expiry sanity query) |
| Re-run duplicates? | impossible by construction (PK conflict-ignore) — verified in integration test |
