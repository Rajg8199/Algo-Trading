"""Shared Prometheus metric definitions.

Services import what they emit; names are defined once here so dashboards
and alert rules have a single vocabulary to reference.
"""

from prometheus_client import Counter, Gauge, Histogram

TICKS_INGESTED = Counter(
    "ticks_ingested_total", "Hot-set ticks written to TimescaleDB", ["underlying"]
)
CHAIN_ROWS_INGESTED = Counter(
    "chain_rows_ingested_total", "Full-chain snapshot rows written", ["underlying"]
)
CHAIN_SNAPSHOT_AGE = Gauge(
    "chain_snapshot_age_seconds", "Age of latest chain snapshot", ["underlying"]
)
WS_RECONNECTS = Counter("ws_reconnects_total", "Market feed websocket reconnects")
WS_CONNECTED = Gauge("ws_connected", "1 when the market feed websocket is up")
VALIDATION_FAILURES = Counter(
    "data_validation_failures_total", "Rows quarantined by validators", ["check"]
)
UPSTOX_REST_LATENCY = Histogram(
    "upstox_rest_latency_seconds", "Upstox REST call latency", ["endpoint"]
)
TOKEN_VALID = Gauge("upstox_token_valid", "1 when the Upstox access token is valid")
JOB_RUNS = Counter("scheduler_job_runs_total", "Scheduler job executions", ["job", "outcome"])
JOB_DURATION = Histogram("scheduler_job_duration_seconds", "Scheduler job duration", ["job"])
ALERTS_SENT = Counter("telegram_alerts_sent_total", "Alerts delivered to Telegram", ["severity"])
DB_WRITE_LATENCY = Histogram("db_write_latency_seconds", "Batch write latency", ["table"])
