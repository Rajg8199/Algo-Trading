"""Equity daily bars table for the breakout scanner.

Plain relational table (daily granularity — no hypertable needed). Identity is
(symbol, trade_date); a secondary index supports per-symbol history scans.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equity_bars",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(14, 4), nullable=False),
        sa.Column("high", sa.Numeric(14, 4), nullable=False),
        sa.Column("low", sa.Numeric(14, 4), nullable=False),
        sa.Column("close", sa.Numeric(14, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'NSEBHAV'"), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "trade_date"),
    )
    op.create_index("ix_equity_bars_symbol_date", "equity_bars", ["symbol", "trade_date"])


def downgrade() -> None:
    op.drop_index("ix_equity_bars_symbol_date", table_name="equity_bars")
    op.drop_table("equity_bars")
