"""End-to-end engine test on synthetic data: a short-straddle strategy sold
on day 1, settled at expiry on day 3. Verifies determinism, cost accounting,
expiry settlement at intrinsic, and risk-engine rejection paths."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from tp_backtest.engine import BacktestConfig, run_backtest
from tp_backtest.fills import FillScenario
from tp_backtest.metrics import compute_metrics

from tp_core.models import OrderIntent, OrderSide, OrderType, TradingMode
from tp_core.strategy import (
    InstrumentMeta,
    MarketState,
    Quote,
    RiskLimits,
    Strategy,
)
from tp_core.timeutils import IST

EXPIRY = date(2026, 6, 16)
LOT = 75

META = {
    1: InstrumentMeta(1, "NIFTY", "OPT", EXPIRY, 24500.0, "CE", LOT),
    2: InstrumentMeta(2, "NIFTY", "OPT", EXPIRY, 24500.0, "PE", LOT),
}


def make_states(days: int = 4, snapshots_per_day: int = 5) -> list[MarketState]:
    """Spot pinned at 24500 until expiry; CE/PE premiums decay linearly."""
    states = []
    start = date(2026, 6, 12)
    d = start
    day_count = 0
    while day_count < days:
        if d.weekday() < 5:
            for i in range(snapshots_per_day):
                ts = datetime.combine(d, time(15, 18), tzinfo=IST) + timedelta(minutes=i)
                decay = 1.0 - 0.3 * day_count
                ce = max(100.0 * decay, 5.0)
                states.append(
                    MarketState(
                        ts=ts,
                        spot={"NIFTY": 24500.0},
                        quotes={
                            1: Quote(1, ce, ce - 0.5, ce + 0.5, delta=0.5),
                            2: Quote(2, ce, ce - 0.5, ce + 0.5, delta=-0.5),
                        },
                        meta=META,
                    )
                )
            day_count += 1
        d += timedelta(days=1)
    return states


class ShortStraddleOnce(Strategy):
    name = "test_straddle"

    def __init__(self, lots: int = 1) -> None:
        self.lots = lots
        self.done = False

    def on_market(self, state: MarketState) -> list[OrderIntent]:
        if self.done:
            return []
        self.done = True
        return [
            OrderIntent(
                strategy=self.name,
                mode=TradingMode.PAPER,
                instrument_id=iid,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                qty=self.lots * LOT,
            )
            for iid in (1, 2)
        ]


def test_short_straddle_profits_when_pinned() -> None:
    config = BacktestConfig(scenario=FillScenario.EXPECTED)
    result = run_backtest(ShortStraddleOnce(), make_states(), config)
    # Sold ~99.x each side day 1, settled at intrinsic 0 at expiry: profit.
    assert result.final_pnl > Decimal(10_000)
    settles = [t for t in result.trades if t.tag == "SETTLE"]
    assert len(settles) == 2
    assert all(t.price == Decimal("0.00") for t in settles)
    assert result.total_costs > Decimal(40)  # 2 orders x brokerage + STT etc.


def test_determinism_byte_identical() -> None:
    config = BacktestConfig(scenario=FillScenario.EXPECTED)
    r1 = run_backtest(ShortStraddleOnce(), make_states(), config)
    r2 = run_backtest(ShortStraddleOnce(), make_states(), config)
    assert r1.final_pnl == r2.final_pnl
    assert [(t.ts, t.price) for t in r1.trades] == [(t.ts, t.price) for t in r2.trades]


def test_best_case_beats_expected_beats_worst() -> None:
    pnls = {}
    for scenario in FillScenario:
        result = run_backtest(ShortStraddleOnce(), make_states(), BacktestConfig(scenario=scenario))
        pnls[scenario] = result.final_pnl
    assert pnls[FillScenario.BEST] >= pnls[FillScenario.EXPECTED] >= pnls[FillScenario.WORST]


def test_risk_engine_blocks_oversized() -> None:
    limits = RiskLimits(max_net_short_options=1)  # 1 lot max; straddle needs 2
    config = BacktestConfig(scenario=FillScenario.BEST, limits=limits)
    result = run_backtest(ShortStraddleOnce(lots=2), make_states(), config)
    assert result.rejected_intents.get("max_net_short_options", 0) >= 1


def test_metrics_computation() -> None:
    config = BacktestConfig(scenario=FillScenario.EXPECTED)
    result = run_backtest(ShortStraddleOnce(), make_states(), config)
    m = compute_metrics(result)
    assert m.net_pnl > 0
    assert m.n_trades == 2  # two settles
    assert m.max_drawdown >= 0
    assert m.total_costs > 0
