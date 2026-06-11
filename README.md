# trading-platform

Quant research and trading platform for Indian index options (NIFTY / SENSEX) on Upstox.
Phase 1 scope: market data recording, batch analytics jobs, Telegram mission control,
observability. Paper/backtest engines arrive in Phase 2; live trading is gated behind
validation criteria and is not wired in this codebase.

## Layout

- `libs/core` — config, domain models, TimescaleDB access, Redis bus, telemetry
- `libs/upstox` — the only package that knows Upstox API shapes (auth, REST, feed)
- `services/recorder` — websocket hot set + 60s full-chain REST snapshots
- `services/scheduler` — cron jobs: token check, instrument refresh, NSE EOD, vol metrics, DQ
- `services/api` — internal read API + Upstox OAuth callback
- `services/telegram` — alert delivery (P1/P2/digest) + read-only commands
- `migrations` — alembic; hypertables/compression/caggs as explicit SQL
- `infrastructure` — docker, caddy, prometheus/grafana/loki/alertmanager, backups
- `datalake` — raw/validated/features/backtests artifact areas (gitignored)

## Quickstart (dev)

```bash
cp .env.example .env          # fill in Upstox + Telegram credentials
make install                  # uv sync + pre-commit
make lint typecheck test      # all green before any commit
docker compose up -d timescaledb redis
make migrate
uv run tp-recorder            # or tp-scheduler / tp-api / tp-telegram
```

## Production (VPS)

```bash
make up                # core stack
make up-monitoring     # + prometheus/grafana/loki/alertmanager
```

Daily operational loop: the scheduler checks the Upstox token at 08:30 IST;
if expired you get a Telegram message with a login link — tap it, approve,
done. A P1 fires if there is no valid token by 09:00.

## Invariants

- TimescaleDB is the single source of truth; ClickHouse (compose profile
  `analytics`) is a read-only research replica.
- Bad market data rows are dropped and counted, never silently stored.
- `option_chain` is never deleted and is the most carefully backed-up asset.
- Every research/backtest run lands in `experiments` with its git SHA and
  trial number. No untracked experiments.
- Telegram commands are read-only until the live phase.
