# VRP Measurement Study — NIFTY (the first credible edge signal)

**Question.** Does ATM implied vol systematically exceed *subsequent* realized
vol on NIFTY (a harvestable volatility-risk premium), and is it conditional on
the IV level? Measurement only — no strategy, no P&L claim.

**Data.** 2024-01 → 2026-06. ATM IV = `atm_iv_front` (EOD settlement, 465 days);
forward realized vol = annualized stdev of NIFTY index log returns over the next
H trading days (index closes synthesized from bhav). `tp_research.options.vrp`,
runner `scripts/vrp_study.py`.

## Result — PREMIUM PRESENT and CONDITIONAL

| Horizon | Mean IV | Mean fwd RV | Mean VRP (vol pts) | Hit rate | low / mid / high-IV mean VRP |
|---|---|---|---|---|---|
| 5d | 14.6% | 10.8% | **+3.73** (med +4.10) | **80%** | +1.28 / +3.64 / **+6.26** |
| 10d | 14.6% | 12.1% | +2.43 | 72% | −0.21 / +1.86 / **+5.60** |
| 21d | 14.5% | 13.0% | +1.52 | 66% | −1.31 / +0.53 / **+5.29** |

IV exceeds forward RV by ~3.7 vol pts/week on 80% of days, and the premium grows
**monotonically with IV level** — textbook VRP. This is mechanically distinct
from the rejected directional strategies (breakout/momentum/mean-reversion): it
is a premium-harvest, not a price-prediction.

## Honest caveats (why this is NOT yet an edge to deploy)

- **Vol points, gross of everything.** Not net P&L. Harvesting requires SELLING
  options → bid/ask + costs, and a **fat left tail**: the ~20% of days where RV
  > IV include gap-downs that can dwarf the accumulated premium. An 80% hit rate
  with a fat tail can still lose (mean-reversion won 61% and lost).
- **EOD/coarse.** Settlement IV is noisier than intraday; entry/exit timing
  untested.
- This is a **measurement**, not a backtest of a tradeable structure.

## Next step (pre-register before building)

Backtest an actual short-vol structure — delta-hedged short straddle or an
iron-condor — entered conditional on IV regime (the high-IV tercile is where the
premium concentrates), using recorded settlement option prices, **with realistic
costs and the full tail losses**, judged on the same REJECT-by-default gate
(expectancy, profit factor, max drawdown, walk-forward stability). Only then is
there a claim. The recorded intraday chains are the eventual upgrade for entry
timing once enough history accrues.
