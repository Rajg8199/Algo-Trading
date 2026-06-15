"""Scalp signal forward-test log.

Persists every emitted scalp signal and its graded outcome (WIN/LOSS/OPEN +
realized R), so the UNVALIDATED scalp engine can be measured live before trust.
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scalp_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("underlying", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("side", sa.String(5), nullable=False),
        sa.Column("entry", sa.Numeric(12, 2), nullable=False),
        sa.Column("stop", sa.Numeric(12, 2), nullable=False),
        sa.Column("target", sa.Numeric(12, 2), nullable=False),
        sa.Column("rsi", sa.REAL()),
        sa.Column("outcome", sa.String(8)),
        sa.Column("exit_price", sa.Numeric(12, 2)),
        sa.Column("r_multiple", sa.REAL()),
        sa.Column("evaluated_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_scalp_signals_unique", "scalp_signals",
        ["underlying", "timeframe", "ts", "side"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_scalp_signals_unique", table_name="scalp_signals")
    op.drop_table("scalp_signals")
