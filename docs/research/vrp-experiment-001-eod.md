# EXPERIMENT 001-EOD — Conditional VRP on free EOD bhavcopy (SCREEN)

**Status: REGISTERED (pre-run). Separate protocol from EXPERIMENT 001 — it
does NOT modify the frozen intraday 001. This is a coarse SCREEN on free data,
not a substitute for intraday validation. A PASS here justifies acquiring
intraday data (GFDL) or running the recorder forward-test; it does NOT advance
a strategy toward paper or live on its own. The live-trading gate is
unchanged and still requires the full intraday Experiment 001.**

## Why this exists

GFDL intraday data is not currently available and TradingView has no Indian
option chains. The only *free* historical option source is NSE/BSE EOD F&O
bhavcopy (official daily settlement prices + OI per strike). This experiment
runs the conditional-VRP hypothesis against that data to answer the cheap
go/no-go question — *does the premium exist and pay on real settlement
prices?* — before spending money on intraday data.

Data is loaded by `tp_research.bhav` (see `docs/data/bhav_import.md`):
settlement price is the mark; IV/Greeks are computed Black-Scholes from
settlement vs the in-row underlying price; lot size comes from the file.

## Hypotheses

Identical H1/H0/economic-rationale to EXPERIMENT 001 §4A. The null is still
"net expectancy ≤ 0 at EXPECTED fills" and the burden of proof is on H1.

## What changes vs intraday 001 (and what it costs)

| Element | Intraday 001 | 001-EOD |
|---|---|---|
| Data source | recorded/GFDL 1-min snapshots, vendor IV, bid/ask | NSE/BSE EOD bhavcopy, settlement only, **no bid/ask** |
| Snapshots/day | many (latency queue replay) | **one** (15:30 IST settlement) |
| IV metric | vendor IV at 15:25 cut | **BSM IV from settlement** vs in-row underlying, CE+PE mean at nearest strike |
| Entry time | one decision 15:18–15:24 | at **daily settlement** |
| Exit / stop | hold-to-expiry, OR intra-trade premium stop, OR intra-trade vov breach (next snapshot) | hold-to-expiry, OR stop checked at **daily settlement only**, OR vov breach checked **EOD** |
| Fills | cross recorded spread + 1.5× slippage + 1-snapshot latency | settlement **± modeled slippage** (no quotes exist) — BEST/EXPECTED/WORST retained, anchored on settlement |

**Lost in EOD (documented limitations):** intraday entry timing; true
premium-stop precision (a stop that would trigger and recover within a day is
invisible); fill microstructure. EOD therefore *understates* path risk and
*overstates* fillability — both bias results optimistically, so a PASS is
necessary-not-sufficient and a FAIL is decisive.

## Fills without quotes

Bhavcopy has no bid/ask. 001-EOD reuses the registered amendment
`BacktestConfig.synthetic_spread_pct` (from the GFDL pipeline): the per-leg
half-spread is modeled as a percent of settlement, calibrated from the
recorder's real spreads once any live data exists. Until calibrated, the
`eod_granularity_blocker` in `bhav.report.readiness_report` stays FAILED.

## Acceptance (same gates, screen semantics)

Every Phase 3F gate (PF>1.5, Sharpe>1.5, maxDD<10%, ≥100 trades, fillability,
Monte Carlo ruin <1%, walk-forward sign stability, regime stability) plus
deflated Sharpe ≥ 0.90 and WORST-scenario expectancy > 0 — evaluated exactly
as 001. The ONLY difference is the decision wiring: a PASS emits
`SCREEN_PASS → acquire intraday data`, never `ADVANCE`.

## Engine support (DONE — no separate adapter needed)

The `tp_backtest` engine turned out to be granularity-agnostic: `run_backtest`
consumes any `Iterable[MarketState]`, latency is counted in *snapshots* (so one
snapshot/day = one-trading-day latency), `Quote.mid` falls back to `ltp` (=
settlement for bhavcopy), expiry settlement is per-day at intrinsic, and the
fill model already has the `synthetic_spread_pct` path for quote-less data.
Because the importer writes exactly one `option_chain` ts/day, `replay_snapshots`
already yields one MarketState/day. Two small plumbing gaps were closed:

1. `VRPParams.decision_start` / `decision_end` (default = intraday 15:18-15:24,
   unchanged). EXP-001-EOD sets `time(15,25)-time(15,35)` to admit the 15:30
   settlement snapshot. Without this the strategy never entered on EOD data.
2. `run_experiment(..., synthetic_spread_pct=...)` now threads into
   `BacktestConfig` (previously the documented amendment was never wired, so
   quote-less fills silently no-filled).

**EOD latency semantics:** EXPECTED/WORST latency = 1 snapshot = **next
trading day's settlement** (you compute the signal from a settlement that is
only final after close, so you cannot trade at that same settlement — modeling
the fill at D+1 settlement is conservative and honest). BEST = same-day.

## Runner (BUILT)

`scripts/run_vrp_experiment_eod.py` runs the registered 72-combo protocol via
`run_experiment_001(base_params=VRPParams(decision_start=15:25, decision_end=
15:35), synthetic_spread_pct=...)`, with `replay_snapshots(..., source="NSEBHAV")`
so only bhavcopy rows are replayed. Regime variable = `iv_percentile_1y` (no
India VIX loaded). Records a normal `experiments` row tagged screen=True.

## First screen result (2025-01-01..2026-06-12, spread 2.0% PROVISIONAL)

DECISION: **INVESTIGATE — no qualifying walk-forward windows.** The registered
filter stack does not fire on this 18-month NIFTY period:
- `iv_percentile_1y ≥ 70` and `term_slope ≥ 0` (contango) are **anti-correlated
  (-0.54)** — high-IV days are typically backwardated — so their intersection
  is only 18 days; VRP≥1 holds on ~all of them.
- those 18 all have `vov_20d > 1.5`: EOD settlement IV is ~2-3× noisier
  day-to-day than an intraday cut (median vov 3.38 vs the gate's 1.0/1.5), so
  the vov gate removes the rest → 0 entries.
- 18 candidates / 18 months is already below the ≥15-trades-per-180-day-window
  floor regardless of vov.
This is a clean refusal, not a pipeline failure — do NOT loosen the frozen grid
to manufacture trades. Legitimate next steps (Raj's call, must be pre-registered
as an amendment): an EOD-calibrated `max_vov` band (justified by the measured
EOD vov distribution), and/or revisiting the high-IV∧contango coupling.

## PROPOSED AMENDMENT — EXP-001-EOD-A2 (NOT registered; awaiting Raj sign-off)

The first screen produced 0 entries for structural reasons, not noise. Three
changes are proposed; each keeps the hypothesis intact and recalibrates only
what is provably scale-mismatched. **Pre-registration cost: any grid expansion
raises trial count → the deflated-Sharpe bar rises (declared here, before any
re-run, on purpose).** Raj picks which to adopt.

1. **Recalibrate `max_vov` to the EOD scale.** Measured EOD vov distribution:
   min 1.22 / p25 2.42 / median 3.38 / p75 4.62. The gate's INTENT is "calm
   vol-of-vol" — on EOD settlement IV (≈2-3× noisier than an intraday cut) the
   equivalent band is **{2.5, 3.5}** (≈ p25/median), replacing {1.0, 1.5}. This
   is a units recalibration, not a loosening.

2. **Make contango a grid dimension, not a hard filter.** `iv_percentile_1y`
   and `term_slope` are anti-correlated (-0.54): high-IV days are usually
   backwardated, so `iv_pct≥70 ∧ contango` is structurally near-empty (18 days
   in 18mo). `require_contango ∈ {True, False}` (already a `VRPParams` field)
   lets the data decide. Grid 72→144 combos; DSR penalty doubles.

3. **(Optional) Lower the IV-percentile band to {50, 70, 90}.** Admits mid-IV
   days; 18 months rarely sustains the ≥70 regime. Changes the "rich IV" intent
   slightly — adopt only if (1)+(2) still under-trade.

Even with (1)+(2), entry count may stay below the ≥100-trade gate on this
period — in which case the honest screen verdict is "EOD NIFTF 2025-26 does not
support this strategy", which is itself a result worth having before spending on
intraday data. Do NOT iterate thresholds beyond one registered amendment.

## Still required before a meaningful screen (Raj-gated)

- **Feature backfill** over the historical bhav range: `atm_iv_front`,
  `har_rv_forecast_1d`, `iv_percentile_1y`, `vov_20d`, `term_slope` must be
  computed into `feature_values` from the imported chain (the strategy reads
  only features, yesterday's by policy). Needs the DB + feature engine run
  over history.
- **Calibrate `synthetic_spread_pct`** from recorded spreads (needs the
  recorder running). Until then a provisional, clearly-flagged value may be
  used for a first screen only.
- An `EXP-001-EOD` entry in the run script wiring the widened window +
  synthetic spread + bhav-source dataset filter.
- Flip the `eod_granularity_blocker` only once the above are real.
