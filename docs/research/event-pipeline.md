# Phase 2E — Event Research Pipeline (specification)

Hypothesis H2 family: scheduled-event IV crush (RBI MPC, Union Budget, FOMC,
US CPI, India CPI). One shared framework; per-event-type reporting.

## 1. Event database

Existing `events` table (event_ts TIMESTAMPTZ, event_type, scheduled,
description, metadata JSONB). Seeded from `docs/data/events.csv` via
`scripts/seed_events.py` (idempotent upsert on ts+type). Conventions:
- `event_ts` = announcement moment IST (RBI ~10:00, Budget 11:00,
  FOMC 23:30/00:00 IST next-day, CPI per release calendar)
- metadata: `{"surprise": null}` updated post-event for surprise regressions
- Calendar maintenance is a quarterly manual job — wrong event times silently
  corrupt every downstream number, so the seed file is reviewed, not scraped.

## 2. Event study methodology

For each event e at time t_e, define windows in TRADING days:
**pre** [t_e−5, t_e), **event** [t_e, t_e+1), **post** (t_e+1, t_e+3].

Per event, compute and persist (table `event_studies`, backlog E-2):
| Measure | Definition |
|---|---|
| iv_runup | ATM IV(t_e−1 close) − ATM IV(t_e−5 close) |
| implied_move | ATM straddle price(t_e−1 close) / spot, % |
| realized_move | abs(close(t_e+1) − close(t_e−1)) / close(t_e−1), % |
| iv_crush | ATM IV(t_e+1 close) − ATM IV(t_e−1 close) |
| term_response | front crush vs next-expiry crush (surface normalization, H10) |
| premium_capture | straddle(t_e−1) − straddle(t_e+1) − realized intrinsic, after costs |

## 3. Event IV analysis

Questions, answered per event type with bootstrap CIs (small N is the rule —
RBI ≈ 8/yr, Budget 1-2/yr; pool across types for power, report per-type):
1. Does IV run up systematically pre-event? (median iv_runup > 0, CI)
2. Is the implied move overpriced? **edge ratio = implied/realized**, median
   and full distribution — the distribution's left tail IS the risk report.
3. How fast is the crush? (t_e+1 vs t_e+3 — exit timing input)

## 4. Event RV analysis

Realized move distribution per event type: median, IQR, max; tail table of
every event where realized > implied (these fund the strategy's losses);
conditional analysis on VIX regime at entry (does high-VIX entry change the
edge ratio?).

## 5. Event premium calculation

Tradeable premium per event = short ATM straddle (defined-risk wings at the
strike grid's 10Δ) entered t_e−1 15:20, exited t_e+1 15:20:
`premium = entry_credit − exit_debit − costs(1.5×)`, marked from recorded
bid/ask, NOT mid. Report: hit rate, mean win, mean loss, worst loss vs mean
win (the lumpiness number), expectancy per event type.

## 6. Acceptance criteria (pre-registered)

Pooled events: expectancy > 0 at 1.5× costs with bootstrap 90% CI excluding
zero, AND worst observed loss < 6× mean win. Otherwise the event family is
shelved — small-N strategies do not get benefit of the doubt.

## 7. Build items

- E-1 `scripts/seed_events.py` + curated CSV ✅ built this phase
- E-2 `event_studies` table + migration (backlog)
- E-3 event-study job: computes §2 measures for any event whose post window
  closed (scheduler, weekly)
- E-4 notebook: per-type edge-ratio distributions (after ≥1 quarter of data
  or purchased history)
