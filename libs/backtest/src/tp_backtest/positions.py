"""Position book for the backtest: average-price accounting, realized PnL on
reductions, expiry settlement at intrinsic value (Indian index options are
cash-settled European)."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from tp_core.models import OrderSide, Position, TradingMode
from tp_core.strategy import InstrumentMeta


@dataclass
class BookEntry:
    qty: int = 0  # signed units
    avg_price: Decimal = Decimal(0)
    realized: Decimal = Decimal(0)


@dataclass
class TradeRecord:
    ts: datetime
    instrument_id: int
    side: str
    qty: int
    price: Decimal
    costs: Decimal
    strategy: str
    tag: str  # OPEN | CLOSE | SETTLE
    realized_pnl: Decimal = Decimal(0)


@dataclass
class PositionBook:
    strategy: str
    entries: dict[int, BookEntry] = field(default_factory=dict)
    trades: list[TradeRecord] = field(default_factory=list)
    total_costs: Decimal = Decimal(0)

    def apply_fill(
        self,
        ts: datetime,
        instrument_id: int,
        side: OrderSide,
        qty: int,
        price: Decimal,
        costs: Decimal,
    ) -> None:
        entry = self.entries.setdefault(instrument_id, BookEntry())
        signed = qty if side is OrderSide.BUY else -qty
        realized = Decimal(0)

        if entry.qty != 0 and (entry.qty > 0) != (signed > 0):
            # Reducing or flipping: realize PnL on the closed portion.
            closed = min(abs(signed), abs(entry.qty))
            direction = 1 if entry.qty > 0 else -1
            realized = (price - entry.avg_price) * closed * direction
            entry.realized += realized
            remaining = entry.qty + signed
            if remaining == 0 or (remaining > 0) == (entry.qty > 0):
                entry.qty = remaining  # pure reduction; avg unchanged
            else:
                entry.qty = remaining  # flipped through zero
                entry.avg_price = price
        else:
            new_qty = entry.qty + signed
            if new_qty != 0:
                entry.avg_price = (
                    (entry.avg_price * abs(entry.qty) + price * abs(signed)) / abs(new_qty)
                ).quantize(Decimal("0.0001"))
            entry.qty = new_qty

        self.total_costs += costs
        self.trades.append(
            TradeRecord(
                ts=ts,
                instrument_id=instrument_id,
                side=side.value,
                qty=qty,
                price=price,
                costs=costs,
                strategy=self.strategy,
                tag="CLOSE" if realized != 0 else "OPEN",
                realized_pnl=realized,
            )
        )

    def settle_expired(
        self, ts: datetime, today: date, meta: dict[int, InstrumentMeta], spot: dict[str, float]
    ) -> None:
        """Cash-settle any open option whose expiry has passed, at intrinsic."""
        for iid, entry in self.entries.items():
            m = meta.get(iid)
            if (
                entry.qty == 0
                or m is None
                or m.segment != "OPT"
                or m.expiry is None
                or m.expiry >= today
                or m.strike is None
            ):
                continue
            s = spot.get(m.underlying)
            if s is None:
                continue
            intrinsic = max(s - m.strike, 0.0) if m.option_type == "CE" else max(m.strike - s, 0.0)
            price = Decimal(str(round(intrinsic, 2)))
            direction = 1 if entry.qty > 0 else -1
            realized = (price - entry.avg_price) * abs(entry.qty) * direction
            entry.realized += realized
            self.trades.append(
                TradeRecord(
                    ts=ts,
                    instrument_id=iid,
                    side="SETTLE",
                    qty=abs(entry.qty),
                    price=price,
                    costs=Decimal(0),
                    strategy=self.strategy,
                    tag="SETTLE",
                    realized_pnl=realized,
                )
            )
            entry.qty = 0

    def unrealized(self, marks: dict[int, float]) -> Decimal:
        total = Decimal(0)
        for iid, entry in self.entries.items():
            if entry.qty == 0:
                continue
            mark = marks.get(iid)
            if mark is None:
                continue
            total += (Decimal(str(round(mark, 2))) - entry.avg_price) * entry.qty
        return total

    @property
    def realized_total(self) -> Decimal:
        return sum((e.realized for e in self.entries.values()), Decimal(0))

    def net_pnl(self, marks: dict[int, float]) -> Decimal:
        return self.realized_total + self.unrealized(marks) - self.total_costs

    def as_positions(self, mode: TradingMode) -> dict[int, Position]:
        return {
            iid: Position(
                mode=mode,
                strategy=self.strategy,
                instrument_id=iid,
                qty=e.qty,
                avg_price=e.avg_price,
                realized_pnl=e.realized,
            )
            for iid, e in self.entries.items()
            if e.qty != 0
        }
