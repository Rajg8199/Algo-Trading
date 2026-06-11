from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from tp_core.models.enums import Exchange, OptionType, Segment


class Instrument(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_id: int | None = None  # None until persisted
    upstox_key: str
    exchange: Exchange
    segment: Segment
    underlying: str
    expiry: date | None = None
    strike: Decimal | None = None
    option_type: OptionType | None = None
    lot_size: int = 1
    tick_size: Decimal | None = None
    is_active: bool = True

    @property
    def is_option(self) -> bool:
        return self.segment is Segment.OPT
