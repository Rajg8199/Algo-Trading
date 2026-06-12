# Phase 2D — Conditional VRP Research Pipeline (specification)

Hypothesis H1 from Phase 0. This document pre-registers the methodology —
formulas, entries, exits, validation — BEFORE the backtest runs. Parameter
ranges declared here are the complete search space; anything outside them is
a new trial and increments the trial counter in `experiments`.

## 1. Exact formula

**VRP(t) = IV_ATM_front(t) − E[RV(t → t+τ)]**, in annualized vol points, where
τ = days to front expiry.

- Signal uses the **forecast** E[RV] (HAR-RV), never future RV (no lookahead).
- Realized VRP for evaluation: `IV_ATM_front(t) − RV_realized(t → expiry)`,
  computed only after expiry passes.

## 2. IV methodology

`atm_iv_front` from the feature engine: vendor IV at 15:25 IST close cut,
mean of CE+PE at the strike nearest spot, both legs required, sane-range
filtered (1–200). Front = nearest weekly (NIFTY Tue / SENSEX Thu).
**Validation prerequisite:** before trusting vendor IV, recompute
Black-Scholes IV from mid prices on 10 sample days and reconcile to vendor IV
within 1 vol point at ATM (backlog item R-1). Divergence ⇒ we compute our own.

## 3. RV methodology

- Forecast: HAR-RV (`har_rv_forecast_1d`) on Parkinson daily RV, horizon
  scaled √τ for multi-day windows.
- Realization: Yang-Zhang over the holding window (captures overnight gaps,
  which close-close misses and which is where short premium dies in India).

## 4. Entry criteria (pre-registered parameter space)

Enter short-premium structure (defined-risk: iron condor / credit spreads —
structure choice is itself a registered parameter) when ALL of:

| Condition | Parameter space |
|---|---|
| VRP percentile (1y) | ≥ {70, 80, 90} |
| Vol-of-vol gate | `vov_20d` percentile ≤ {50, 70} |
| Event exclusion | no RBI/Budget/FOMC within τ days: {on, off} |
| Entry time | 15:20 IST (close cut), T+0 after signal |
| Days to expiry | enter only if τ ∈ {2..5} (skip 0-1 DTE) |

## 5. Exit criteria

- Hold to expiry (base case), OR
- Stop: structure loss ≥ {1.5, 2.0}× credit received
- Vol stop: `vov_20d` crosses above gate intra-trade ⇒ exit next close cut
- No profit-target exits in v1 (adds a parameter; earn it later)

## 6. Regime filters

`vix_percentile_1y` bands {low <30, mid 30-70, high >70}: report performance
per band; the strategy must not be a one-regime wonder. `term_slope` < 0
(inversion) is a hard no-trade — backwardation marks stress.

## 7. Validation methodology

1. **Costs**: full Indian stack (brokerage, STT sell-side, exchange, GST,
   stamp) at 1×/1.5×/2× slippage on recorded bid-ask. Must survive 1.5×.
2. **Minimum sample**: 150 trades before any conclusion (weekly cadence ⇒
   needs purchased history; see §10).
3. **Deflated Sharpe** using the trial count from `experiments`.
4. **Regime stratification** + structural-break splits (Nov 2024 lot sizes,
   Sept 2025 expiry change).
5. **Tail audit**: P&L on the 10 worst recorded vol days, marked at worst
   intraday quotes, not closes.

## 8. Walk-forward framework

Anchored walk-forward: train 12m → validate 3m → step 3m. Parameters chosen
on train by median net Sharpe; validation segments concatenated = the only
reported equity curve. Purging: 1 expiry-cycle gap between train/validate
(positions span days; naive splits leak).

## 9. Monte Carlo framework

- Trade-sequence bootstrap (block size = 1 expiry week, 10k resamples) →
  drawdown distribution, P(maxDD > 10%), risk-of-ruin at proposed sizing.
- Skip-jitter: drop each trade w.p. 10% → fragility to missed fills.
- Acceptance: 95th-percentile maxDD < 15% of allocated capital.

## 10. Requirements summary

| Item | Source | Status |
|---|---|---|
| Features: atm_iv_front, har_rv_forecast_1d, vov_20d, iv_percentile_1y, term_slope, vix_percentile_1y | feature engine | ✅ built (accumulating) |
| Event calendar | events table + seed script | ✅ built |
| Realized-VRP evaluation job (post-expiry) | new scheduler job | backlog R-2 |
| Backtest engine + cost model | Phase 2 backlog B-1..B-3 | not built |
| Historical 1-min chains 2021-2026 (GFDL) | purchase | **blocking for full validation**; own recording covers forward-test only |
| `experiments` registry | Phase 1 | ✅ |
