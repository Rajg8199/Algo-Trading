"""Event schemas for everything that crosses Redis. Versioned by field `v`."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from tp_core.models.enums import Severity
from tp_core.timeutils import now_utc


class TickEvent(BaseModel):
    v: Literal[1] = 1
    ts: datetime
    instrument_id: int
    underlying: str
    ltp: float
    bid: float | None = None
    ask: float | None = None
    oi: int | None = None


class ChainSnapshotEvent(BaseModel):
    """Lightweight notification that a fresh full-chain snapshot landed in the DB.
    Consumers query the DB for the payload — snapshots are too big for the bus."""

    v: Literal[1] = 1
    ts: datetime
    underlying: str
    expiry: str
    row_count: int


class AlertEvent(BaseModel):
    v: Literal[1] = 1
    ts: datetime = Field(default_factory=now_utc)
    severity: Severity
    source: str
    dedup_key: str
    message: str
