# Short-Term Mean-Reversion Screen — Pre-Registration (H-MR-01)

> Written BEFORE the first run. Gate frozen here. Tested once on split-adjusted
> data; a re-tune is a new experiment, not an edit.

## Hypothesis

Buying short-term oversold dips **in an uptrend** and selling the bounce has
positive expectancy net of costs on liquid NSE equities. This is mechanically
the OPPOSITE of the rejected breakout (buy strength) — and the 2024-26 chop that
whipsawed breakouts is exactly the regime mean-reversion is meant to exploit.

## Design (frozen)

- **Universe**: median 120-day turnover ≥ ₹5 cr; ≥ 201 days history;
  split/bonus-adjusted bars.
- **Entry** (next open after the signal close): close > 200-DMA (uptrend) AND
  RSI(2) < 10 (oversold).
- **Exit** (next open): close reclaims the 5-DMA (the bounce), OR 10-trading-day
  time stop, whichever first.
- **Disaster stop**: close − 3 × ATR(14), checked intraday.
- **Costs**: 0.2% round-trip. Sizing: 1% risk/trade (for the equity curve).

## Acceptance gate (REJECT by default)

All must hold:
1. ≥ 30 trades, expectancy > 0.1R, profit factor > 1.3, max drawdown < 25%
   (same bar as H-BRK-01), **and**
2. **walk-forward stability**: expectancy > 0 in EACH of 3 equal calendar
   periods (not one lucky window).

PASS → PROMISING (still not auto-live). Else REJECT.

## Result — REJECT (UNVALIDATED)

Run on split-adjusted bars, 2024-26, 960 liquid symbols, 18,836 trades:

| Metric | Value | Gate | Pass |
|---|---|---|---|
| Trades | 18,836 | ≥30 | ✓ |
| Win rate | 60.9% | — | (high, as expected) |
| Expectancy | 0.00 R | >0.1R | ✗ |
| Profit factor | 0.88 | >1.3 | ✗ |
| Avg win / loss | +0.26R / −0.39R | — | small wins, bigger losses |
| Max drawdown | 97.8% | <25% | ✗ |
| Total return | +6.6% | — | |

**Walk-forward (3 periods):** −0.03R / +0.03R / −0.00R — not all-positive, not
stable.

**Verdict: REJECT.** Textbook mean-reversion shape — wins often (61%) but the
small wins don't cover costs + the fatter losses, so expectancy is ~0 and the
edge flips sign across periods. The walk-forward breakdown is the tell: a single
in-sample number (+6.6% total) hid an unstable, no-edge strategy.

Three strategies now tested (breakout, momentum, mean-reversion), all REJECTED
on this universe/period. Consistent with the platform's premise; none promoted.
