"""Conditional Variance Risk Premium strategy (hypothesis H1).

Pre-registered logic per docs/research/vrp-pipeline.md:
- Signal: VRP = atm_iv_front - har_rv_forecast_1d (vol points), entered only
  when all conditional filters pass.
- Structure: defined-risk iron condor — sell ~25Δ CE+PE, buy ~10Δ wings.
- Exits: hold to expiry (engine settles at intrinsic), hard stop at
  stop_mult x entry credit, vol-stop when vov gate trips intra-trade.

The strategy reads ONLY MarketState (features are yesterday's by dataset
policy — no same-day leakage). It never sees the database or the future.
"""

from dataclasses import dataclass
from datetime import date, time

from tp_core.models import OrderIntent, OrderSide, OrderType, TradingMode
from tp_core.strategy import InstrumentMeta, MarketState, Quote, Strategy
from tp_core.timeutils import IST

DECISION_START = time(15, 18)
DECISION_END = time(15, 24)


@dataclass(frozen=True)
class VRPParams:
    underlying: str = "NIFTY"
    min_vrp_points: float = 2.0  # IV - HAR-RV forecast, vol points
    min_iv_percentile: float = 70.0
    max_vov: float = 1.5  # vol-of-vol gate (vol points of daily IV change)
    require_contango: bool = True  # term_slope >= 0
    max_client_net_puts: float | None = None  # optional participant filter
    dte_min: int = 2
    dte_max: int = 5
    short_delta: float = 0.25
    wing_delta: float = 0.10
    stop_mult: float = 2.0  # exit at loss >= stop_mult x credit
    lots: int = 1


@dataclass
class _OpenStructure:
    instrument_ids: list[int]
    credit: float  # estimated entry credit, rupees
    entry_day: date


class ConditionalVRP(Strategy):
    def __init__(self, params: VRPParams) -> None:
        self.params = params
        self.name = f"vrp_{params.underlying.lower()}"
        self._open: _OpenStructure | None = None
        self._last_action_day: date | None = None

    # ── helpers ──────────────────────────────────────────────────────────
    def _filters_pass(self, state: MarketState) -> bool:
        p = self.params

        def f(name: str) -> float | None:
            return state.feature(p.underlying, name)

        iv = f("atm_iv_front")
        rv_forecast = f("har_rv_forecast_1d")
        iv_pct = f("iv_percentile_1y")
        vov = f("vov_20d")
        slope = f("term_slope")
        if iv is None or rv_forecast is None or iv_pct is None or vov is None:
            return False  # missing inputs = no trade, never a default
        if iv - rv_forecast < p.min_vrp_points:
            return False
        if iv_pct < p.min_iv_percentile:
            return False
        if vov > p.max_vov:
            return False
        if p.require_contango and (slope is None or slope < 0):
            return False
        if p.max_client_net_puts is not None:
            client_puts = f("client_net_idx_puts")
            if client_puts is not None and client_puts > p.max_client_net_puts:
                return False
        return True

    def _pick_expiry(self, state: MarketState, today: date) -> date | None:
        expiries = sorted(
            {
                m.expiry
                for m in state.meta.values()
                if m.segment == "OPT"
                and m.underlying == self.params.underlying
                and m.expiry is not None
                and self.params.dte_min <= (m.expiry - today).days <= self.params.dte_max
            }
        )
        return expiries[0] if expiries else None

    @staticmethod
    def _nearest_by_delta(
        legs: list[tuple[InstrumentMeta, Quote]], option_type: str, target: float
    ) -> tuple[InstrumentMeta, Quote] | None:
        best: tuple[float, tuple[InstrumentMeta, Quote]] | None = None
        for m, q in legs:
            if m.option_type != option_type or q.delta is None or q.mid is None:
                continue
            dist = abs(abs(q.delta) - target)
            if best is None or dist < best[0]:
                best = (dist, (m, q))
        if best is None or best[0] > 0.08:
            return None
        return best[1]

    def _build_condor(
        self, state: MarketState, expiry: date
    ) -> tuple[list[OrderIntent], float] | None:
        p = self.params
        legs = state.options(p.underlying, expiry)
        short_ce = self._nearest_by_delta(legs, "CE", p.short_delta)
        short_pe = self._nearest_by_delta(legs, "PE", p.short_delta)
        wing_ce = self._nearest_by_delta(legs, "CE", p.wing_delta)
        wing_pe = self._nearest_by_delta(legs, "PE", p.wing_delta)
        if not all((short_ce, short_pe, wing_ce, wing_pe)):
            return None
        assert short_ce and short_pe and wing_ce and wing_pe
        if wing_ce[0].instrument_id in (short_ce[0].instrument_id,) or wing_pe[0].instrument_id in (
            short_pe[0].instrument_id,
        ):
            return None  # degenerate grid: wing collapsed onto short strike

        lot = short_ce[0].lot_size
        qty = p.lots * lot
        intents = []
        credit = 0.0
        for (m, q), side in (
            (short_ce, OrderSide.SELL),
            (short_pe, OrderSide.SELL),
            (wing_ce, OrderSide.BUY),
            (wing_pe, OrderSide.BUY),
        ):
            assert q.mid is not None
            credit += q.mid * qty * (1 if side is OrderSide.SELL else -1)
            intents.append(
                OrderIntent(
                    strategy=self.name,
                    mode=TradingMode.PAPER,
                    instrument_id=m.instrument_id,
                    side=side,
                    order_type=OrderType.MARKET,
                    qty=qty,
                    signal_snapshot={
                        "leg": f"{side.value}_{m.option_type}_{m.strike}",
                        "delta": q.delta,
                    },
                )
            )
        if credit <= 0:
            return None
        return intents, credit

    def _structure_pnl(self, state: MarketState) -> float | None:
        assert self._open is not None
        total = 0.0
        for iid in self._open.instrument_ids:
            pos = state.positions.get(iid)
            quote = state.quotes.get(iid)
            if pos is None or pos.qty == 0:
                continue
            if quote is None or quote.mid is None or pos.avg_price is None:
                return None  # can't mark: don't guess
            total += (quote.mid - float(pos.avg_price)) * pos.qty
        return total

    def _close_all(self, state: MarketState) -> list[OrderIntent]:
        assert self._open is not None
        intents = []
        for iid in self._open.instrument_ids:
            pos = state.positions.get(iid)
            if pos is None or pos.qty == 0:
                continue
            intents.append(
                OrderIntent(
                    strategy=self.name,
                    mode=TradingMode.PAPER,
                    instrument_id=iid,
                    side=OrderSide.BUY if pos.qty < 0 else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=abs(pos.qty),
                    signal_snapshot={"reason": "stop"},
                )
            )
        return intents

    # ── main entrypoint ──────────────────────────────────────────────────
    def on_market(self, state: MarketState) -> list[OrderIntent]:
        local = state.ts.astimezone(IST)
        today = local.date()
        p = self.params

        # Expiry passed? engine settled it; clear our handle.
        if self._open is not None and not any(
            state.positions.get(iid) for iid in self._open.instrument_ids
        ):
            self._open = None

        # Stop management on every snapshot while open.
        if self._open is not None:
            pnl = self._structure_pnl(state)
            vov = state.feature(p.underlying, "vov_20d")
            stop_hit = pnl is not None and pnl <= -p.stop_mult * self._open.credit
            vov_stop = vov is not None and vov > p.max_vov and today > self._open.entry_day
            if stop_hit or vov_stop:
                intents = self._close_all(state)
                self._open = None
                self._last_action_day = today
                return intents
            return []

        # Entry: once per day, in the decision window only.
        if self._last_action_day == today:
            return []
        if not (DECISION_START <= local.time() <= DECISION_END):
            return []
        self._last_action_day = today

        if not self._filters_pass(state):
            return []
        expiry = self._pick_expiry(state, today)
        if expiry is None:
            return []
        built = self._build_condor(state, expiry)
        if built is None:
            return []
        intents, credit = built
        self._open = _OpenStructure(
            instrument_ids=[i.instrument_id for i in intents],
            credit=credit,
            entry_day=today,
        )
        return intents
