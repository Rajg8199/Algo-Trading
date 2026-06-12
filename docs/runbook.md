# OPERATIONS RUNBOOK — First Recording Day

Single-engineer guide: from cloned repo to continuous market-data recording.
Verified against the codebase at the commit that ships this file (the Docker
image builds, alembic + entrypoints + seed scripts confirmed inside it).

---

## TASK 1 — Deployment readiness checklist

### Services that must be running (core stack)

| Service | Type | Health |
|---|---|---|
| timescaledb | container | `pg_isready` (compose healthcheck) |
| redis | container | `redis-cli ping` (compose healthcheck) |
| migrate | one-shot | exits 0 after `alembic upgrade head` |
| recorder | daemon | `:8001/ready` — components db/redis/feed |
| scheduler | daemon | `:8002/ready` |
| api | daemon | `:8000/ready` |
| telegram | daemon | `:8003/ready` |
| caddy | container | only needed for the OAuth callback over a domain (see Task 2 option B) |

Monitoring stack (`docker-compose.monitoring.yml`) is optional for day 1 but
recommended: prometheus, alertmanager, grafana, loki, promtail, node-exporter,
postgres-exporter.

### Environment variables (`.env`, from `.env.example`)

| Variable | Secret? | Notes |
|---|---|---|
| POSTGRES_HOST/PORT/DB/USER | no | host=`timescaledb` inside compose |
| POSTGRES_PASSWORD | **yes** | generate: `openssl rand -hex 16` |
| REDIS_HOST/PORT | no | host=`redis` inside compose |
| UPSTOX_API_KEY | **yes** | from Upstox developer app |
| UPSTOX_API_SECRET | **yes** | from Upstox developer app |
| UPSTOX_REDIRECT_URI | no | MUST byte-match the app config (Task 2) |
| UPSTOX_REST_RATE_LIMIT_PER_SEC | no | keep 20 until plan limits verified |
| UPSTOX_WS_MAX_INSTRUMENTS | no | keep 400 until plan limits verified |
| TELEGRAM_BOT_TOKEN | **yes** | from BotFather (Task 3) |
| TELEGRAM_ALLOWED_CHAT_ID | **yes** | your numeric chat id (Task 3) |
| API_PORT / *_HEALTH_PORT | no | defaults 8000–8003 |
| RECORDER_* | no | defaults fine for day 1 |
| ENVIRONMENT / LOG_LEVEL | no | `prod` / `INFO` on the VPS |

### Network ports

- **Public:** 80/443 (caddy) — ONLY if using option B for OAuth. Nothing else.
- Internal docker network: 5432, 6379, 8000–8003. Never publish these on a VPS.
- Dev laptop only: `docker-compose.dev.yml` publishes 127.0.0.1:5432 / :6380.

### External dependencies

1. Upstox developer app (api key/secret) — Task 2
2. Telegram bot — Task 3
3. Outbound HTTPS to: `api.upstox.com`, `assets.upstox.com`,
   `nsearchives.nseindia.com`, `api.telegram.org`
4. Host: Docker + Docker Compose v2; 4 vCPU / 8 GB / 200 GB NVMe; **system
   timezone irrelevant** (code is tz-aware) but NSE EOD job assumes the
   published-by-IST-evening calendar
5. (Backups) rclone configured with remote `b2` — can follow day 1

---

## TASK 2 — Upstox setup

1. **Create the app:** <https://account.upstox.com/developer/apps> → New App.
   Fields: name (anything), **Redirect URL** (critical, below), postback URL
   (leave blank). The app gives you **API Key** and **API Secret** → `.env`.
2. **Redirect URI — pick one:**
   - **Option A (first run, no domain):** `http://localhost:8000/api/v1/auth/upstox/callback`.
     You will complete login in a browser on the VPS via SSH port-forward:
     `ssh -L 8000:localhost:8000 user@vps` — then "localhost" resolves
     correctly on your laptop. If Upstox rejects plain-http localhost at app
     creation, use Option B.
   - **Option B (proper):** `https://YOUR-DOMAIN/api/v1/auth/upstox/callback`
     with caddy running and DNS pointed at the VPS (Caddyfile already routes
     exactly this path to the api service).
   - The `.env` `UPSTOX_REDIRECT_URI` must match the app field **exactly**
     (scheme, host, path, no trailing slash).
3. **OAuth flow (what our code does):** scheduler's `token_check` job (08:30 +
   09:00 IST) validates the stored token against `/user/profile`; if invalid
   it Telegrams you a login link (`/login/authorization/dialog?...`). You tap
   → Upstox login (phone + TOTP + PIN) → redirect hits our callback → token
   exchanged and stored in the `auth_tokens` table → Telegram confirms
   "✅ Upstox token refreshed".
4. **Manual fallback** (callback unreachable, e.g. redirect lands on a dead
   localhost tab): copy the `code=` parameter from the browser address bar,
   then on the VPS:
   `curl "http://localhost:8000/api/v1/auth/upstox/callback?code=PASTE_CODE"`
   (run within ~1 minute; auth codes are short-lived).
5. **Validation:** `curl -s localhost:8000/api/v1/status | grep upstox` →
   `"upstox_token": "valid"`. Tokens die daily ~03:30 IST — the morning
   Telegram link is your daily 10-second ritual.

---

## TASK 3 — Telegram setup

1. In Telegram, message **@BotFather** → `/newbot` → pick name + username →
   copy the token → `TELEGRAM_BOT_TOKEN`.
2. No special permissions; it's a private 1:1 bot. Do not add it to groups.
3. **Chat ID:** send any message to your new bot, then:
   `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"id":[0-9]*' | head -1`
   → that number is `TELEGRAM_ALLOWED_CHAT_ID`. (The bot ignores every other
   chat id by design.)
4. **Verify:** after services start, send `/health` to the bot → expect
   `🟢 db ✓ · redis ✓`. Send `/status` → data freshness summary.

---

## TASK 4 — First deployment runbook

Run as a non-root user with docker access, in order. ☐ = success criterion.

**1. Clone + configure**
```bash
git clone <your-repo-remote> trading-platform && cd trading-platform
cp .env.example .env && nano .env    # fill every secret from Tasks 1-3
```
☐ `grep -c '^[A-Z].*=$' .env` returns 0 (no empty required values).
Diagnosis: services later crash-looping with pydantic ValidationError = a
missing/empty env value; the error names the field.

**2. Build + start data layer**
```bash
docker compose up -d timescaledb redis
docker compose ps
```
☐ Both `Up (healthy)` within ~30s.
Diagnosis: timescaledb unhealthy → `docker compose logs timescaledb`; most
common is a previous pgdata volume with a different password
(`docker volume rm trading-platform_pgdata` ONLY if fresh install).

**3. Migrations**
```bash
docker compose up migrate
```
☐ Exits 0; log shows `Running upgrade -> 0001`.
☐ Verify: `docker compose exec timescaledb psql -U trading -d trading -c "\dt" | wc -l` → ~20 lines.
Diagnosis: `relation already exists` = re-run after partial apply; check
`alembic_version` table contents.

**4. Seed instruments (required BEFORE recorder start)**
```bash
docker compose run --rm api python scripts/seed_instruments.py
```
☐ Output like `seeded 14xx instruments: {'INDEX': 3, 'FUT': ..., 'OPT': ...}` —
INDEX must be 3 (NIFTY, SENSEX, India VIX).
Diagnosis: `parsed only N instruments` → Upstox master format drifted; this
is finding #1 of the known-unverified parsers — inspect
`https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz`
and fix `tp_upstox.rest.download_instrument_master` field mapping.

**5. Seed events (optional day 1)** — verify dates in `docs/data/events.csv`
first (remove `VERIFY:` flags), then
`docker compose run --rm api python scripts/seed_events.py docs/data/events.csv`.

**6. Start everything**
```bash
docker compose up -d --build
docker compose ps
```
☐ recorder, scheduler, api, telegram all `Up`; recorder may show `(unhealthy)`
until the token exists — expected.
☐ Telegram receives a P1: "Recorder started without a valid Upstox token" —
this proves the alert pipeline works before the market does.

**7. Complete OAuth** — Task 2 flow.
☐ Telegram: "✅ Upstox token refreshed". ☐ `/api/v1/status` shows token valid.

**8. Verify recorder (during market hours)**
```bash
curl -s localhost:8001/ready
docker compose logs recorder --since 5m | grep -E 'feed_connected|subscription_set_built|tick_rejected'
```
☐ `"ready": true`, `subscription_set_built instruments=<300-400>`,
`feed_connected`.
Diagnosis: `feed_disconnected` loops → see Task 7 playbook 2. Off-hours, the
feed is quiet and `ready` stays true by design.

**9. Verify database writes (market hours)**
```bash
docker compose exec timescaledb psql -U trading -d trading -c \
 "SELECT (SELECT count(*) FROM ticks WHERE ts > now()-interval '5 min') ticks_5m,
         (SELECT count(*) FROM option_chain WHERE ts > now()-interval '5 min') chain_5m;"
```
☐ ticks_5m > 1000, chain_5m > 500 (two underlyings × ~3 expiries × ~100 rows/min).
Diagnosis: ticks>0 but chain=0 → chain poller failing → playbook 3.

**10. Verify Telegram end-to-end**
☐ `/status` answers with fresh timestamps. ☐ 09:20 heartbeat arrives (Task 5).

---

## TASK 5 — First market day timeline (IST)

| Time | Running | Check | Expected |
|---|---|---|---|
| **08:00** | full stack idle | `docker compose ps` all Up; disk >20% free | no errors overnight in `docker compose logs --since 12h \| grep -i error` |
| **08:30** | scheduler `token_check` fires | Telegram login link arrives (if token expired ~03:30) — **tap it now** | "✅ token refreshed" |
| **09:00** | `token_check_late` | if you ignored 08:30, second P1 link; token MUST be valid before open | `/api/v1/status` token=valid |
| **09:15** | market open; feed connects | recorder logs `feed_connected`; `ws_connected=1` on `:8001/metrics` | first ticks within seconds |
| **09:20** | heartbeat job | Telegram: `❤️ recorder: N ticks / M chain rows in last 5m · db ✓` | N>1000, M>500 |
| **10:00** | steady state | DB: ~45min recorded | ticks ≈ 50–150k rows; option_chain ≈ 25–50k rows; `chain_snapshot_age_seconds` < 120 |
| **12:00** | steady | 12:30 heartbeat will follow; spot-check `/status` | open_data_gaps = 0 (or each explained by a logged reconnect) |
| **15:30** | market close | 15:35 heartbeat = day's last | full-day totals: ticks 300k–1M; option_chain ≈ 600k rows |
| **16:00** | `vol_metrics` (16:00) + `feature_engine` (16:15) | Telegram INFO: features computed (coverage will be LOW day 1 — ~20–30% is correct, history features need time) | `feature_values` has rows for today |
| **18:00** | digest + `nse_eod` retries from 18:30 | INFO digest arrives; participant OI lands by ~19:30 | `participant_oi` rows for today (or playbook: NSE file format = known-unverified parser #3) |
| **21:00** | `data_validation` | DQ report in Telegram | day 1 realistic: completeness PASS, some P2s acceptable; any P1 → Task 6 queries |

---

## TASK 6 — Post-market validation SQL

Run after 21:30 IST. Replace dates as needed. Thresholds = the registered
DQ framework thresholds.

```sql
-- 1. Ticks collected (PASS: >=50,000 per underlying)
SELECT i.underlying, count(*) FROM ticks t JOIN instruments i USING (instrument_id)
WHERE t.ts::date = current_date GROUP BY 1;

-- 2. Chain snapshots (PASS: >=10,000 rows AND >=300 distinct minutes per underlying)
SELECT i.underlying, count(*) AS rows, count(DISTINCT t.ts) AS snapshots
FROM option_chain t JOIN instruments i USING (instrument_id)
WHERE t.ts::date = current_date GROUP BY 1;

-- 3. Greeks populated (PASS: >=90% of near-ATM rows have delta AND iv)
SELECT i.underlying,
       round(100.0 * count(*) FILTER (WHERE t.delta IS NOT NULL AND t.iv IS NOT NULL)
             / count(*), 1) AS pct_with_greeks
FROM option_chain t JOIN instruments i USING (instrument_id)
WHERE t.ts::date = current_date
  AND t.spot IS NOT NULL AND i.strike BETWEEN t.spot*0.97 AND t.spot*1.03
GROUP BY 1;

-- 4. OI populated (PASS: >=95% rows non-null, max(oi) > 0)
SELECT i.underlying,
       round(100.0 * count(t.oi) / count(*), 1) AS pct_with_oi, max(t.oi) AS max_oi
FROM option_chain t JOIN instruments i USING (instrument_id)
WHERE t.ts::date = current_date GROUP BY 1;

-- 5. Feature generation (PASS day 1: >=8 features per underlying;
--    history features legitimately absent)
SELECT entity, count(*) AS features_computed
FROM feature_values WHERE ts::date = current_date GROUP BY 1;

-- 6. DQ checks (PASS: zero failed P1-class checks; review every row here)
SELECT check_name, passed, details FROM dq_checks
WHERE check_date = current_date ORDER BY passed, check_name;

-- 7. Gap audit (PASS: each gap matches a logged ws reconnect)
SELECT * FROM data_gaps WHERE detected_at::date = current_date;
```

Day-1 verdict: queries 1–4 and 6 at PASS = **the recording day counts**.
Anything failed → fix tonight, because tomorrow's data has the same bug.

---

## TASK 7 — Incident playbooks

**1. Upstox auth failure** (P1 `token_invalid` repeats / exchange fails)
Diagnose: `docker compose logs api | grep token_exchange_failed`.
- 400/invalid_grant → code expired (60s) or redirect URI mismatch → redo
  login fast; confirm `.env` URI == app URI byte-for-byte, then
  `docker compose up -d api scheduler` after any `.env` change.
- 401 on key/secret → regenerate secret in the developer portal.
- Login page loops → Upstox-side; retry; check their status page.
Recovery is always: complete one clean OAuth round; recorder resumes alone
(it polls for the token every 30s; no restart needed).

**2. WebSocket disconnect loops** (`ws_reconnects_total` climbing)
Expected behavior: backoff 1→60s, REST snapshot bridges each gap, P2 alert.
Investigate when >5 reconnects/30min: `docker compose logs recorder | grep feed_`.
- `401/403` in error → token died mid-day → playbook 1.
- Connects then instant-drops → likely instrument-key or limit problem →
  reduce `UPSTOX_WS_MAX_INSTRUMENTS` to 200, restart recorder, re-test.
- Network → `docker compose exec recorder curl -sI https://api.upstox.com` from
  inside the container.
Data impact check afterwards: query 7 (gaps) + chain rows for the window.

**3. No option chain data** (ticks flowing, option_chain empty)
`docker compose logs recorder | grep chain_poll_failed` — read the exception.
- `no valid Upstox token` → playbook 1.
- HTTP 429 → halve `UPSTOX_REST_RATE_LIMIT_PER_SEC`, restart recorder.
- `chain_rows_unknown_instruments` high → instrument master stale → run
  seed_instruments.py again (new strikes listed intraday are picked up next
  morning by design).
- Empty `data` in response → expiry param mismatch → check
  `SELECT min(expiry) FROM instruments WHERE underlying='NIFTY' AND expiry >= current_date AND segment='OPT'`
  is a real upcoming Tuesday.

**4. Missing strikes** (DQ `missing_strikes_*` failing)
- Compare instrument count vs chain rows for the front expiry; if instruments
  exist but rows don't, the REST response is partial → log one raw response
  (temporary debug) and check whether Upstox paginates beyond N strikes.
- If instruments are missing entirely → master parse dropped them (strike
  field format) → fix parser, reseed, document in docs/decisions/.

**5. Redis outage**
Symptoms: services' `/ready` shows redis ✗; alerts stop (DB writes CONTINUE —
recording is not lost).
`docker compose restart redis` → verify `docker compose exec redis redis-cli ping` = PONG.
Alerts queued in the stream survive restart (AOF on); telegram consumer
group resumes. If the volume is corrupt: `docker volume rm trading-platform_redis-data`
loses only undelivered alerts, never market data.

**6. Database outage** — THE serious one; recording stops.
`docker compose logs timescaledb --tail 50`.
- OOM-killed → check `docker stats`; raise VPS RAM or lower
  `shared_buffers`; restart.
- Disk full → `df -h`; emergency space: delete old local backup gz files,
  never the pgdata volume. Compression policy should be keeping up — verify
  `SELECT * FROM timescaledb_information.jobs`.
- Won't start / corrupt → restore newest dump into a fresh volume
  (`infrastructure/backup/restore_drill.sh` is the template) — accept the gap,
  record it in data_gaps manually.
While DB is down the recorder buffers ~500 rows then drops with
`tick_flush_failed` logs; every minute down is a permanent gap → treat as P1
even at 2 AM if it's still down by 08:30.

**7. Telegram outage** (alerts undelivered)
Recording is unaffected. Alerts accumulate durably in the Redis stream
(maxlen 10k) and deliver on recovery.
- `docker compose logs telegram --tail 30`: 401 = token revoked → new
  BotFather token → `.env` → `docker compose up -d telegram`.
- 409 conflict = two bot instances polling → `docker compose ps` for a
  duplicate; kill one.
- api.telegram.org unreachable → wait; check `/ready` on :8003.
Until fixed, your eyes are: `:8001/ready`, the SQL in Task 6, and
`docker compose logs -f recorder`.

---

*Escalation default: if recording is healthy, do nothing until 15:31. The
only intervention that can't wait for market close is the DB (playbook 6)
and a dead token before 09:15 (playbook 1).*
