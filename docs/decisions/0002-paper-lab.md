# ADR 0002 — Paper Trading Lab before ADVANCE verdict (owner override)

## Context

ADR-0001 / Experiment-001 gated paper trading behind an ADVANCE verdict.
On 2026-06-12 the owner directed paper trading to begin immediately, in
parallel with research.

## Decision

Build it as a **Forward-Test Lab**, reframed so the original gate's intent
(no unvalidated strategy is treated as validated) survives:

1. Every signal is labeled **UNVALIDATED · forward-test** in Telegram and UI.
2. Paper results are forward-test EVIDENCE for Experiment 001's successor
   analyses — never a substitute for the validation gate. Lab PnL does not
   promote a strategy.
3. The learning layer recommends parameter changes ONLY from the registered
   Experiment-001 grid, only at ≥30 closed orders, and every recommendation
   carries requires_approval=true. The single deployment path is a human
   editing `datalake/paper/params.json`.
4. The engine reuses the exact backtest stack (strategy, risk engine, EXPECTED
   fill model on real recorded bid/ask, cost model) — so lab fills double as
   the spread-calibration evidence the GFDL readiness blocker needs.
5. **The live-trading gate is unchanged and untouched.** No broker order
   modules exist in services/paper.

## Status

Implemented (services/paper, scheduler paper_review 16:30 IST, console
endpoints, dashboard page).
