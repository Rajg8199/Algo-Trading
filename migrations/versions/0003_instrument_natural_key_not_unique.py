"""Drop the natural-key unique constraint on instruments.

One economic contract may legitimately carry two vendor keys — a historical-
synthetic key from the EOD bhavcopy backfill (NSEBHAV|…) and a live Upstox key
(NSE_FO|…). Identity is the vendor key (upstox_key, still unique); the natural
key (exchange, underlying, segment, expiry, strike, option_type) must not be
unique, or seeding the live instrument master collides with backfilled rows.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_CONSTRAINT = "instruments_exchange_underlying_segment_expiry_strike_optio_key"


def upgrade() -> None:
    op.execute(f"ALTER TABLE instruments DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE instruments ADD CONSTRAINT {_CONSTRAINT} "
        "UNIQUE (exchange, underlying, segment, expiry, strike, option_type)"
    )
