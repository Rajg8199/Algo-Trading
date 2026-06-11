# ADR 0001 — Phase 1 architecture (approved 2026-06-12)

## Decisions

1. **Hybrid market data capture.** WebSocket "full" mode for the hot set
   (indices, VIX, near futures, ATM±15 strikes × 2 expiries); REST option-chain
   poll at 60s for the complete chain incl. Greeks/OI. WS subscription and REST
   rate budgets are configuration (`UPSTOX_WS_MAX_INSTRUMENTS`,
   `UPSTOX_REST_RATE_LIMIT_PER_SEC`), set conservatively until verified against
   the live account's plan limits.
2. **TimescaleDB is the single source of truth.** ClickHouse (compose profile
   `analytics`) is an optional, read-only research replica of option_chain
   history, loaded by a batch sync script. Nothing operational reads ClickHouse.
3. **Reproducibility is schema-enforced.** `experiments` records every
   research/backtest run with git SHA, params, cost multiplier, and a
   per-hypothesis `trial_number` (input to deflated Sharpe). `feature_values`
   keys every feature by (name, version) so research is replayable.
4. **Semi-manual daily Upstox re-auth.** Tokens die ~03:30 IST daily; headless
   refresh is unsupported. Scheduler checks 08:30/09:00 IST and sends a
   one-tap login link via Telegram; FastAPI hosts the OAuth callback.
5. **One strategy interface across runtimes.** Strategies emit OrderIntents;
   the risk layer and BrokerAdapter interface are shared by backtest, paper,
   and (future) live engines. Live trading is not wired in Phase 1.
6. **Research/backtesting are libraries, not daemons.** Only recorder,
   scheduler, api, and telegram run continuously.
7. **Single Mumbai VPS, no HA.** Mitigation: alerting (Prometheus/Alertmanager
   → Telegram), nightly encrypted off-site backups, monthly scripted restore
   drills. Revisit before live capital.
8. **Official Upstox SDK owns the protobuf wire format only.** Our adapter
   owns reconnect policy, parsing into typed quotes, and validation. SDK touch
   points are isolated to `tp_upstox.feed.MarketFeed.connect`, covered by a
   `live_creds`-marked smoke test rather than CI.

## Status

Implemented in the Phase 1 scaffold. Pending first live-market validation:
feed message shape (fixture-based parser tests exist; field names must be
confirmed against a captured live session), NSE participant-OI CSV column
names, Upstox instrument-master field names.
