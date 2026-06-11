"""Initial schema: relational tables from ORM metadata + TimescaleDB DDL.

Hypertables, compression, retention, and the 1-min continuous aggregate are
raw SQL — they are TimescaleDB-specific and deliberately explicit.
"""

import sqlalchemy as sa
from alembic import op

from tp_core.db.orm import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TIMESCALE_DDL = [
    "CREATE EXTENSION IF NOT EXISTS timescaledb",
    # ── ticks: hot-set tick data ──────────────────────────────────────────
    "SELECT create_hypertable('ticks','ts', chunk_time_interval => INTERVAL '1 day', migrate_data => true)",
    """ALTER TABLE ticks SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'ts'
    )""",
    "SELECT add_compression_policy('ticks', INTERVAL '3 days')",
    "SELECT add_retention_policy('ticks', INTERVAL '180 days')",
    # ── option_chain: full-chain minute snapshots (kept forever) ─────────
    "SELECT create_hypertable('option_chain','ts', chunk_time_interval => INTERVAL '1 day', migrate_data => true)",
    """ALTER TABLE option_chain SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'ts'
    )""",
    "SELECT add_compression_policy('option_chain', INTERVAL '7 days')",
    # ── feature_values: hypertable on ts for range scans ─────────────────
    "SELECT create_hypertable('feature_values','ts', chunk_time_interval => INTERVAL '30 days', migrate_data => true)",
]

CAGG_DDL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS bars_1m
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', ts) AS bucket,
       instrument_id,
       first(ltp, ts)  AS open,
       max(ltp)        AS high,
       min(ltp)        AS low,
       last(ltp, ts)   AS close,
       last(volume, ts) AS volume,
       last(oi, ts)    AS oi
FROM ticks
GROUP BY bucket, instrument_id
WITH NO DATA
"""

CAGG_POLICY = """
SELECT add_continuous_aggregate_policy('bars_1m',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute')
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    for stmt in TIMESCALE_DDL:
        op.execute(stmt)
    # Continuous aggregates cannot run inside the migration transaction.
    with op.get_context().autocommit_block():
        op.execute(CAGG_DDL)
        op.execute(CAGG_POLICY)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS bars_1m CASCADE")
    Base.metadata.drop_all(op.get_bind())
