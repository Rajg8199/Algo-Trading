"""The strategy contract. One interface, three runtimes: backtest replays
recorded snapshots through it, the paper engine feeds it live snapshots,
a future live engine does the same. Strategies never touch the database,
the broker, or the clock — everything arrives in MarketState.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from tp_core.models import OrderIntent, Position


@dataclass(frozen=True)
class Quote:
    """Tradeable state of one instrument at one moment."""

    instrument_id: int
    ltp: float | None
    bid: float | None
    ask: float | None
    iv: float | None = None
    delta: float | None = None
    oi: float | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.ask >= self.bid:
            return (self.bid + self.ask) / 2
        return self.ltp


@dataclass(frozen=True)
class InstrumentMeta:
    instrument_id: int
    underlying: str
    segment: str  # INDEX | FUT | OPT
    expiry: date | None = None
    strike: float | None = None
    option_type: str | None = None  # CE | PE
    lot_size: int = 1


@dataclass
class MarketState:
    """Everything a strategy may know at time ts. No future data, ever."""

    ts: datetime
    spot: dict[str, float]  # underlying -> spot
    quotes: dict[int, Quote]  # instrument_id -> quote
    meta: dict[int, InstrumentMeta]
    features: dict[str, dict[str, float]] = field(default_factory=dict)  # entity -> name -> value
    positions: dict[int, Position] = field(default_factory=dict)
    cash_pnl: Decimal = Decimal(0)

    def feature(self, entity: str, name: str) -> float | None:
        return self.features.get(entity, {}).get(name)

    def options(self, underlying: str, expiry: date) -> list[tuple[InstrumentMeta, Quote]]:
        out = []
        for iid, m in self.meta.items():
            if (
                m.segment == "OPT"
                and m.underlying == underlying
                and m.expiry == expiry
                and iid in self.quotes
            ):
                out.append((m, self.quotes[iid]))
        return out


class Strategy(ABC):
    """Implementations are pure decision functions over MarketState."""

    name: str = "unnamed"

    @abstractmethod
    def on_market(self, state: MarketState) -> list[OrderIntent]:
        """Called on every snapshot. Return intents (possibly empty)."""

    def on_session_end(self, state: MarketState) -> list[OrderIntent]:
        """Called at each session's final snapshot; default no action."""
        return []
