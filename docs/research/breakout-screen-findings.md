# Equity Breakout Screen — Findings (UNVALIDATED, do not deploy)

**Hypothesis (H-BRK-01).** A Donchian/Turtle-style long breakout on liquid NSE
equities — close above the prior N-day high, with a 50/200-SMA trend filter, a
volume-confirmation, and an ATR-chandelier stop — has positive expectancy net
of costs.

**Data.** NSE UDiFF CM bhavcopy, 2024-01-01 → 2026-06-12: 1,397,398 daily bars,
602 trading days, 2,981 symbols (`equity_bars`, ingested via
`tp_research.equity`). Liquid universe = median 120-day turnover ≥ ₹5cr (957
symbols) or ≥ ₹10cr (716 leaders).

**Method.** No lookahead (signal at close → entry next open); gap/stop/target/
ATR-trail exits; round-trip cost 0.2%; reported in R-multiples plus a
fixed-fractional (1% risk/trade) equity curve ordered by exit date. Engine:
`tp_research.screener`; runner: `scripts/breakout_backtest.py`.

## Result — REJECT

| Config | Trades | Win% | Expectancy | PF | Max DD | Total | Gate |
|---|---|---|---|---|---|---|---|
| Baseline 20d, no regime | 2,298 | 31.8% | −0.05R | 0.80 | 96% | −78.6% | FAIL |
| + market-regime filter | 1,855 | 31.9% | −0.04R | 0.79 | 94% | −67.1% | FAIL |
| regime + 55d + ≥₹10cr | 1,146 | 33.8% | +0.03R | 0.84 | 77% | +6.4% | FAIL |

Acceptance gate (REJECT-by-default): ≥30 trades ∧ expectancy >0.1R ∧ PF >1.3 ∧
maxDD <25%. **No configuration passes.**

## Interpretation

- 31–34% win rate at ~2:1 avg win/loss → negative expectancy after costs. The
  filters (regime, slower breakout, liquid leaders) move the result from
  clearly-losing toward breakeven but never to an edge; PF stays < 1 and the
  drawdown is disqualifying. The best "total return" (+6.4%) is noise riding a
  77% drawdown, not a tradeable system.
- 2024–2026 was a rally→correction regime — high whipsaw for breakouts. A
  different/longer sample may differ, but that is not grounds to deploy now.
- **This was NOT p-hacked to a pass.** Three pre-specified, theory-grounded
  configs were tested once each; all failed; exploration stopped. A pass found
  by grid-searching would be fake under deflated-Sharpe reasoning.

## Decision

Signals page stays **UNVALIDATED**. The simple breakout is not promoted to
alerts as an edge. The ingestion + scanner + backtest infrastructure is sound
and reusable; the *edge* is absent. Any future attempt must be a distinct,
pre-registered hypothesis (e.g. a different strategy class), not a re-tuning of
this one.
