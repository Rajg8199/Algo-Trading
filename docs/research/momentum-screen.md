# Cross-Sectional Momentum Screen — Pre-Registration (H-MOM-01)

> Written BEFORE the first backtest run. Thresholds are frozen here. A pass is
> only a pass against these numbers; changing them after seeing results = a new
> experiment (H-MOM-02), not a tweak.

## Hypothesis

Long-only **cross-sectional 12-1 momentum** on liquid NSE equities —
rank by trailing-12-month return skipping the most recent month, hold the
top names equal-weight, rebalance monthly, with a market-trend overlay
(hold cash when the broad market is below its 200-DMA) — outperforms an
equal-weight benchmark of the same universe, net of costs.

Rationale: momentum is the most replicated equity anomaly globally and is
documented in Indian equities. It is *mechanically distinct* from the rejected
breakout (H-BRK-01): cross-sectional ranking + monthly horizon vs single-name
daily trend. The 2024–26 chop that whipsawed breakouts does not a priori kill a
monthly relative-strength rotation.

## Design (frozen)

- **Universe**: median 120-day turnover ≥ ₹5 cr; ≥ 273 trading days of history.
- **Score**: `close[t-21] / close[t-252] - 1` (12-1; skip last month to dodge
  short-term reversal).
- **Selection**: each rebalance, rank eligible symbols desc; hold the top decile,
  clamped to [15, 40] names, equal-weight.
- **Regime overlay**: equal-weight market index (built from the universe) below
  its 200-DMA → portfolio goes to cash for that month.
- **Rebalance**: every 21 trading days.
- **Costs**: 0.2% charged on the turned-over fraction each rebalance.
- **Benchmark**: equal-weight return of all eligible names each period.

## Acceptance gate (REJECT by default)

All four must hold, else **REJECT** (stays UNVALIDATED):

1. ≥ 18 rebalances (sample),
2. annualized return **> benchmark** annualized return (real outperformance),
3. annualized Sharpe (rf = 0) **> 0.8**,
4. max drawdown **< 35 %** (long-only equity tolerance).

PASS → **PROMISING** (not auto-live; short sample, single regime). Anything less
→ REJECT, and no edge is claimed in alerts.

## Result — REJECT (UNVALIDATED)

Run on `equity_bars` 2024-01-01..2026-06-12, 926 liquid symbols, regime ON:

| Metric | Value | Gate | Pass |
|---|---|---|---|
| Rebalances | 16 | ≥ 18 | ✗ |
| Ann. return | 7.2% | > benchmark | ✗ |
| Benchmark ann. | 8.5% | — | — |
| Excess | −1.2%/yr | > 0 | ✗ |
| Sharpe | 0.63 | > 0.8 | ✗ |
| Max drawdown | 8.3% | < 35% | ✓ |
| Hit rate | 44% of months | — | — |

**Verdict: REJECT.** Momentum was defensive (shallow 8.3% drawdown through a
correction) but did **not** beat equal-weight buy-and-hold, on a sample too
short to validate regardless (16 monthly periods after the 273-day warmup;
2024–26 is a single regime). Not evidence that momentum is dead — evidence that
*this window does not support an edge claim*. No promotion. The gate held.

Like H-BRK-01, this was tested once against the frozen gate and not re-tuned.
Any retry must be a new pre-registered hypothesis on a longer / different sample.
