-- Optional analytics layer. TimescaleDB stays the operational source of truth;
-- ClickHouse holds a read-only replica of option_chain history for large
-- research scans. Loaded by scripts/sync_clickhouse.py (batch, idempotent).
CREATE DATABASE IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.option_chain
(
    ts            DateTime64(3, 'UTC'),
    instrument_id UInt32,
    underlying    LowCardinality(String),
    expiry        Date,
    strike        Decimal(10, 2),
    option_type   LowCardinality(String),
    ltp           Nullable(Decimal(12, 2)),
    bid           Nullable(Decimal(12, 2)),
    ask           Nullable(Decimal(12, 2)),
    volume        Nullable(UInt64),
    oi            Nullable(UInt64),
    iv            Nullable(Float32),
    delta         Nullable(Float32),
    gamma         Nullable(Float32),
    theta         Nullable(Float32),
    vega          Nullable(Float32),
    spot          Nullable(Decimal(12, 2))
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (underlying, expiry, strike, option_type, ts);
