"""GFDL import bookkeeping: one row per vendor file, enabling resumable and
auditable imports. Re-importing a 'done' file is skipped; partial files are
safe to retry because all data inserts are conflict-ignoring on PK.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS import_files (
            file_path     TEXT PRIMARY KEY,
            batch_id      TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'pending',
            rows_total    BIGINT,
            rows_imported BIGINT,
            rows_rejected BIGINT,
            error         TEXT,
            started_at    TIMESTAMPTZ,
            finished_at   TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_import_files_batch ON import_files (batch_id, status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS import_files")
