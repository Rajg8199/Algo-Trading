"""Risk engine: every OrderIntent passes through here before any fill, in
every runtime. Strategies cannot bypass it — the engines own the wiring.
"""

from dataclasses import dataclass
from decimal import Decimal

from tp_core.models import OrderIntent, OrderSide
from tp_core.strategy.base import InstrumentMeta, MarketState


@dataclass(frozen=True)
class RiskLimits:
    max_open_lots_per_underlying: int = 10
    max_net_short_options: int = 20  # lots, absolute
    max_daily_loss: Decimal = Decimal(-50_000)  # stop trading for the day below this
    max_total_loss: Decimal = Decimal(-150_000)  # kill switch
    allow_naked_short: bool = False  # defined-risk only until explicitly lifted


@dataclass(frozen=True)
class RiskVerdict:
    accepted: bool
    reason: str | None = None


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self._killed = False

    @property
    def killed(self) -> bool:
        return self._killed

    def validate(self, intent: OrderIntent, state: MarketState) -> RiskVerdict:
        if self._killed:
            return RiskVerdict(False, "kill_switch_active")

        if state.cash_pnl <= self.limits.max_total_loss:
            self._killed = True
            return RiskVerdict(False, "total_loss_kill_switch")

        if state.cash_pnl <= self.limits.max_daily_loss:
            return RiskVerdict(False, "daily_loss_limit")

        meta = self._meta(intent, state)
        if meta is None:
            return RiskVerdict(False, "unknown_instrument")

        lots = self._underlying_lots(state, meta.underlying)
        intent_lots = intent.qty // max(meta.lot_size, 1)
        if lots + intent_lots > self.limits.max_open_lots_per_underlying:
            return RiskVerdict(False, "max_open_lots")

        if intent.side is OrderSide.SELL and meta.segment == "OPT":
            net_short = self._net_short_option_lots(state)
            if net_short + intent_lots > self.limits.max_net_short_options:
                return RiskVerdict(False, "max_net_short_options")

        return RiskVerdict(True)

    @staticmethod
    def _meta(intent: OrderIntent, state: MarketState) -> InstrumentMeta | None:
        return state.meta.get(intent.instrument_id)

    @staticmethod
    def _underlying_lots(state: MarketState, underlying: str) -> int:
        total = 0
        for iid, pos in state.positions.items():
            meta = state.meta.get(iid)
            if meta is not None and meta.underlying == underlying and pos.qty != 0:
                total += abs(pos.qty) // max(meta.lot_size, 1)
        return total

    @staticmethod
    def _net_short_option_lots(state: MarketState) -> int:
        total = 0
        for iid, pos in state.positions.items():
            meta = state.meta.get(iid)
            if meta is not None and meta.segment == "OPT" and pos.qty < 0:
                total += abs(pos.qty) // max(meta.lot_size, 1)
        return total
