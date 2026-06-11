from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class Tick(BaseModel):
    """A hot-set quote update (index, future, or near-ATM option)."""

    model_config = ConfigDict(frozen=True)

    ts: datetime
    instrument_id: int
    ltp: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_qty: int | None = None
    ask_qty: int | None = None
    volume: int | None = None
    oi: int | None = None


class ChainRow(BaseModel):
    """One option in a full-chain snapshot from the REST poll."""

    model_config = ConfigDict(frozen=True)

    ts: datetime
    instrument_id: int
    ltp: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_qty: int | None = None
    ask_qty: int | None = None
    volume: int | None = None
    oi: int | None = None
    oi_prev_day: int | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    spot: Decimal | None = None
