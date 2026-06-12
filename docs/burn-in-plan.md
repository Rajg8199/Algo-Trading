# 10-DAY PRODUCTION BURN-IN PLAN

Purpose: prove the data platform is reliable BEFORE any research conclusion
is trusted. No research runs on burn-in data until the exit criteria pass.

Daily verdict tool (run after 21:15 IST, after the validation job):

```bash
docker compose run --rm api python scripts/burnin_check.py
```

Exit code 0/1/2 = GREEN/YELLOW/RED. Log each day's verdict in the table at
the bottom of this file (edit it daily — it's the burn-in record).

---

## Status criteria

- **GREEN** — every category green. No action.
- **YELLOW** — ≥1 yellow, no red. Diagnose same evening; fix before next
  open if a parser/config issue; acceptable if externally caused (exchange
  half-day, Upstox outage) and documented.
- **RED** — ≥1 red category, or recording missed >15 consecutive market
  minutes, or token invalid past 09:15. The day does NOT count toward
  burn-in; root-cause before next session.

## Monitoring thresholds (per underlying, full session)

| Category | GREEN | YELLOW | RED | Source |
|---|---|---|---|---|
| Recorder ticks/day | ≥100k | 50–100k | <50k | burnin_check `ticks_*` |
| Chain rows/day | ≥100k | 30–100k | <30k | `chain_rows_*` |
| Snapshot minutes | ≥350 | 300–349 | <300 | `snapshot_minutes_*` |
| Max chain gap | ≤120s | 121–180s | >180s | `max_chain_gap_s_*` |
| WS disconnects (data_gaps/day) | ≤3 | 4–10 | >10 | `ws_gaps_today` |
| Missing near-ATM strikes | <2% | 2–5% | >5% | dq `missing_strikes_*` |
| Stale index ticks (max gap) | ≤30s | 31–60s | >60s | dq `stale_ticks_*` |
| Invalid Greeks (chain-wide) | <0.5% | 0.5–1% | >1% | dq `invalid_greeks_*` |
| Invalid IV (near-ATM) | <2% | 2–5% | >5% | `invalid_iv_atm_*` |
| Greeks coverage near-ATM | ≥95% | 90–95% | <90% | `greeks_coverage_*` |
| OI coverage | ≥98% | 95–98% | <95% | `oi_coverage_*` |
| DQ framework | 0 fails | P2 fails only | any P1 fail | `dq_checks` |
| Features/day/entity | ≥10 (day 1–5), ≥12 (day 6+) | ≥6 | <6 | `features_*` |

History-dependent features (iv_percentile, iv_rank, vov, HAR-RV) stay absent
for weeks — that is correct, not a failure; the thresholds above already
account for it.

### Manual SQL (when you want raw numbers rather than the board)

All queries live in `docs/runbook.md` Task 6 and inside
`scripts/burnin_check.py` (the script IS the reference implementation of
every threshold above).

---

## Day 1 checklist (first recording day)

The highest-touch day. Budget attention 08:15–10:00 and 15:30–21:30.

| When | Verify |
|---|---|
| 08:15 | `docker compose ps` all Up; `migrate` exited 0; instruments seeded (`INDEX: 3`) |
| 08:30 | Telegram token link arrives → complete OAuth → ✅ confirmation |
| 09:15 | recorder log `feed_connected`, `subscription_set_built instruments=300–400` |
| 09:20 | first heartbeat: N>1000 ticks, M>500 chain rows |
| 09:30 | **First-contact parser audit:** `docker compose logs recorder --since 20m \| grep -cE 'tick_rejected\|chain_rows_unknown'` — a flood (>100) means the feed/master parser mis-maps fields → capture 5 sample log lines, fix same day |
| 10:00 | spot-check one chain row by hand vs the Upstox app/TradingView: same LTP ballpark, sane IV, non-zero OI |
| 15:35 | closing heartbeat; day totals in range (ticks 300k–1M, chain ≈300–600k total) |
| 16:20 | feature engine INFO alert; `feature_values` has today's rows |
| 19:30 | participant OI landed (`SELECT count(*) FROM participant_oi WHERE trade_date=current_date` ≥ 12) — if 0, NSE CSV parser needs its first-contact fix |
| 21:15 | `burnin_check.py` → expect **YELLOW** day 1 (DQ thresholds are tuned for steady state); every yellow/red must have a written cause |

Expected DB growth day 1: pgdata +0.5–1.5 GB uncompressed (compression kicks
in after 3–7 days). Expected alerts: morning token link, ✅ refresh, 3
heartbeats, feature INFO, DQ report, evening digest. Anything ELSE (P1/P2)
is a finding.

## Days 2–5 checklist (daily, ~10 minutes)

| When | Verify |
|---|---|
| 08:30 | token ritual (tap link) — measure: did it take <60s? |
| 09:20 | heartbeat arrived with sane numbers (glance, don't dig) |
| 15:35 | closing heartbeat |
| 21:15 | `burnin_check.py`; log verdict; diagnose any non-green |

Phase-specific items:
- **First Tuesday (NIFTY expiry):** after close verify (a) no chain rows
  recorded for the expired contract on Wednesday (`expiry_consistency` DQ
  check covers this), (b) Wednesday 08:45 subscription set picked up the new
  front weekly (`subscription_set_built` count similar to before), (c) total
  OI jump on rollover did NOT trip `oi_consistency` falsely — if it did,
  paste the numbers; the same-expiry comparison should have excluded it.
- **First Thursday (SENSEX expiry):** same checks for SENSEX.
- **Weekend:** Saturday + Sunday must be SILENT (no heartbeats, no false
  P1s). Any weekend alert = scheduler calendar bug → fix Monday-blocking.
- Day 3+: confirm TimescaleDB compression is running:
  `SELECT count(*) FROM timescaledb_information.chunks WHERE is_compressed;` ≥ 1.

## Days 6–10 checklist (prove hands-off stability)

Target: the platform runs itself; your only touch is the morning token tap.

| Item | Standard |
|---|---|
| Daily routine | token tap + 21:15 burnin_check ONLY; zero other interventions |
| Verdicts | GREEN every day 6–10; one externally-caused YELLOW tolerated with documentation |
| Day 6 or 7 | run a **backup + restore drill**: `make backup && make restore-drill` → row counts match; this is the first drill against real data |
| Day 8 | disk trajectory check: `docker system df` + pgdata volume size — extrapolate 90 days; must be <40% of disk |
| Day 9 | review `data_gaps` for the whole burn-in: every row must map to a logged reconnect; unexplained gaps = RED finding |
| Day 10 | full Task-6 (runbook) SQL sweep across ALL 10 days, not just the day — per-day row counts within ±30% of the 10-day median (excluding expiry days, which run hotter) |

---

## 10-DAY PRODUCTION BURN-IN — EXIT CRITERIA

The platform is declared reliable, and research may begin consuming the
data, only when ALL of the following hold:

1. **≥8 of 10 days GREEN**, and **zero RED days in days 6–10**.
2. **Zero P1 DQ failures in days 6–10.**
3. Every `data_gaps` row across the period is explained by a logged
   reconnect or a documented external outage.
4. The three first-contact parsers (feed fields, instrument master,
   participant CSV) each ran ≥5 consecutive days without a fix.
5. Backup restore drill passed against real recorded data.
6. Token ritual succeeded all 10 mornings before 09:15 (the one daily
   human dependency is proven workable).
7. Disk/RAM trajectory supports ≥90 days unattended.

On exit: tag the repo (`git tag burn-in-complete`), record the 10-day
verdict table below in the commit, and only then point research at the data.

## Burn-in log (edit daily)

| Day | Date | Verdict | Notes |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8 | | | |
| 9 | | | |
| 10 | | | |
