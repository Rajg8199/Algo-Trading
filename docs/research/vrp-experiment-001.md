# EXPERIMENT 001 — Conditional VRP, NIFTY weeklies

**Status: REGISTERED (pre-run). This file is frozen once the first trial
executes. Any change after that point requires EXPERIMENT 002.**

## 4A — Hypotheses

- **H1 (research):** Selling defined-risk NIFTY weekly option premium,
  conditional on (a) rich implied-vs-forecast-realized vol, (b) calm
  vol-of-vol, (c) non-inverted term structure, produces positive net
  expectancy after realistic costs and fills.
- **H0 (null):** Net expectancy of the conditional strategy at EXPECTED
  fills (spread-crossing, 1.5x slippage, 1-snapshot latency) is ≤ 0.
  **We attempt to fail to reject H0.** The burden of proof is on H1.
- **Economic rationale:** Indian retail option-buying flow (SEBI-documented
  ₹1L-crore annual losses) structurally overpays for convexity; VRP is a risk
  premium for warehousing tail risk, not an arbitrage — it should persist but
  pay only when conditioning avoids the regimes where the tail bites.
- **Failure conditions (any ⇒ hypothesis damaged):** OOS expectancy ≤ 0 at
  EXPECTED fills; profitability concentrated in one VIX regime; >5% of
  entries unfillable; Monte Carlo ruin probability > 1%; sign instability
  across walk-forward windows (≥40% of windows negative).
- **Acceptance conditions:** every Phase 3F gate passes on walk-forward OOS
  results, AND deflated Sharpe ≥ 0.90 given total registered trials, AND
  WORST-scenario expectancy > 0.

## 4B — Exact strategy specification (mirrors `tp_backtest.strategies.vrp`)

| Element | Specification |
|---|---|
| IV metric | `atm_iv_front`: vendor IV at 15:25 IST cut, CE+PE mean at strike nearest spot, both legs required, range (1,200) |
| RV metric | `har_rv_forecast_1d`: HAR-RV OLS on Parkinson daily RV, leakage-safe (yesterday's value) |
| Entry signal | ALL of: `atm_iv_front − har_rv_forecast_1d ≥ min_vrp_points`; `iv_percentile_1y ≥ min_iv_percentile`; `vov_20d ≤ max_vov`; `term_slope ≥ 0`; entry day not excluded by event filter |
| Entry time | One decision per day, 15:18–15:24 IST snapshot |
| Position structure | Iron condor: SELL ~0.25Δ CE + PE, BUY ~0.10Δ CE + PE wings; delta-match tolerance 0.08, else no trade |
| Strike selection | Nearest-|delta| from recorded chain; degenerate grids (wing=short) ⇒ no trade |
| Expiry selection | Front NIFTY weekly with 2 ≤ DTE ≤ 5 (no 0–1 DTE entries) |
| Exit | Hold to expiry (cash settle at intrinsic), OR stop at loss ≥ stop_mult × entry credit, OR vov gate breach intra-trade (exit next snapshot, earliest next day) |
| Risk controls | RiskEngine: ≤10 lots/underlying, ≤20 net short option lots, daily loss −₹50k halts, total −₹150k kill switch; engine-enforced, not strategy-trusted |

## 4C — Parameter search space (REGISTERED — nothing else may be tested)

| Parameter | Values | n |
|---|---|---|
| min_vrp_points | 1.0, 2.0, 3.0 | 3 |
| min_iv_percentile | 70, 80, 90 | 3 |
| max_vov (vol pts) | 1.0, 1.5 | 2 |
| event_exclusion | on, off | 2 |
| stop_mult | 1.5, 2.0 | 2 |
| **Total combinations** | | **72** |

Fixed (not searched): deltas 0.25/0.10, DTE 2–5, lots=1, decision window,
underlying=NIFTY.

**Registered amendment vs Phase 2D draft (made pre-run, hence allowed):**
the draft conditioned on "VRP percentile {70,80,90}"; the implemented filter
is absolute `min_vrp_points` {1,2,3} + `iv_percentile_1y` {70,80,90}, because
a VRP-percentile feature has no recorded history yet. Recorded here so the
trial count and search space stay honest.

**Multiple-testing adjustment:** total trials for this experiment = 72 (full
grid, counted once across walk-forward reuse) + any prior H1-VRP trials in
the `experiments` registry. Deflated Sharpe (Bailey & López de Prado) is
computed against that trial count; the registry assigns trial numbers
atomically so the denominator cannot shrink.

## 4D — Experiment sequence (fixed order, no skipping forward)

1. **Preflight** — dataset fingerprint; ≥120 distinct trading days of chain
   snapshots; DQ pass rate ≥95% over the range; else ABORT (no trial burned).
2. **In-sample grid** — all 72 combos, full range, EXPECTED fills. Purpose:
   trial accounting + parameter-surface sanity (cliff-edge maxima ⇒ suspect).
3. **Walk-forward** — rolling 180d train / 60d validate, 7d purge,
   expiry-snapped. Per window: select combo by highest train net Sharpe with
   ≥15 train trades (weekly cadence makes ~26/window the ceiling; tie →
   lower stop_mult). Concatenated validation segments = the ONLY equity
   curve that counts.
4. **Monte Carlo** — block bootstrap (block=5, 10k paths, seed=42) on OOS
   trade PnLs: drawdown 95/99/99.9, ruin at ₹150k.
5. **Regime testing** — OOS daily PnL stratified by VIX percentile
   (<30 / 30–70 / >70); no bucket with ≥15 days may be net-negative.
6. **Cost stress** — selected combos re-run on validation segments under
   BEST and WORST; report all three; judge on EXPECTED; WORST expectancy
   sign reported in the decision.

## 4F — Decision framework (evaluated in this order)

| Outcome | Exact conditions |
|---|---|
| **REJECT** (terminal for v1) | ANY of: OOS expectancy ≤ 0; MC ruin > 1%; ≥2 regime buckets negative; unfillable > 5%; ≥40% of WF windows with negative validation PnL |
| **ADVANCE TO PAPER** | ALL Phase 3F gates pass on OOS, AND deflated Sharpe ≥ 0.90, AND WORST-scenario expectancy > 0 |
| **PROMISING** | Not ADVANCE, but: OOS Sharpe ≥ 1.0 AND expectancy > 0 AND maxDD ≤ 12% AND no regime bucket < −0.5 Sharpe AND ≥60 OOS trades. Action: extend data, re-run THIS grid — no new parameters |
| **INVESTIGATE** | Anything else with OOS expectancy > 0, or sample < 60 trades. Action: diagnose data/fills/regime sensitivity; no promotion, no tuning |

No outcome may be upgraded manually. A REJECT of this specification is a
*successful experiment* — H1 v1 dies and stays dead; new economics required
for a v2.
