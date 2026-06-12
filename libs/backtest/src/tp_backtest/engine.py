"""Event-driven replay engine.

Determinism contract:
- No randomness anywhere in the engine or fill models (seeds matter only in
  Monte Carlo, which runs on the OUTPUT of this engine).
- Same snapshots + same strategy + same config => byte-identical results.
- dataset_version (fingerprint of the replayed data) is stamped on results
  so an experiment can never silently run on different data.

Latency: intents accepted at snapshot t are filled using the quote at
snapshot t+L (L from the fill scenario). Orders whose instrument has no
usable quote at fill time are DROPPED and counted — unfillable is a result.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from tp_backtest.costs import option_trade_costs
from tp_backtest.fills import FillScenario, fill_price, latency_snapshots
from tp_backtest.positions import PositionBook, TradeRecord
from tp_core.models import OrderIntent, TradingMode
from tp_core.strategy import MarketState, RiskEngine, RiskLimits, Strategy


@dataclass(frozen=True)
class BacktestConfig:
    scenario: FillScenario
    capital: Decimal = Decimal(1_000_000)
    limits: RiskLimits = field(default_factory=RiskLimits)
    dataset_version: str = "unversioned"
    seed: int = 42  # recorded for provenance; engine itself is deterministic


@dataclass
class BacktestResult:
    strategy: str
    scenario: FillScenario
    config: BacktestConfig
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    daily_pnl: dict[date, Decimal] = field(default_factory=dict)
    trades: list[TradeRecord] = field(default_factory=list)
    total_costs: Decimal = Decimal(0)
    rejected_intents: dict[str, int] = field(default_factory=dict)
    unfillable_orders: int = 0

    @property
    def final_pnl(self) -> Decimal:
        return self.equity_curve[-1][1] if self.equity_curve else Decimal(0)


def run_backtest(
    strategy: Strategy, snapshots: Iterable[MarketState], config: BacktestConfig
) -> BacktestResult:
    book = PositionBook(strategy=strategy.name)
    risk = RiskEngine(config.limits)
    latency = latency_snapshots(config.scenario)
    pending: list[tuple[OrderIntent, int]] = []  # (intent, snapshots_remaining)
    result = BacktestResult(strategy=strategy.name, scenario=config.scenario, config=config)

    current_day: date | None = None
    day_start_pnl = Decimal(0)
    last_state: MarketState | None = None

    for state in snapshots:
        today = state.ts.date()
        if current_day is not None and today != current_day:
            result.daily_pnl[current_day] = _equity(book, last_state) - day_start_pnl
            day_start_pnl = _equity(book, last_state)
        if current_day != today:
            current_day = today
            book.settle_expired(state.ts, today, state.meta, state.spot)

        # Inject portfolio view into the state the strategy sees.
        state.positions = book.as_positions(TradingMode.PAPER)
        state.cash_pnl = _equity(book, state)

        # Fill matured pending orders at THIS snapshot's quotes.
        still_pending: list[tuple[OrderIntent, int]] = []
        for intent, remaining in pending:
            if remaining > 0:
                still_pending.append((intent, remaining - 1))
                continue
            _execute(intent, state, book, result, config)
        pending = still_pending

        # Ask the strategy for new intents.
        for intent in strategy.on_market(state):
            verdict = risk.validate(intent, state)
            if not verdict.accepted:
                key = verdict.reason or "unknown"
                result.rejected_intents[key] = result.rejected_intents.get(key, 0) + 1
                continue
            if latency == 0:
                _execute(intent, state, book, result, config)
            else:
                pending.append((intent, latency - 1))

        result.equity_curve.append((state.ts, _equity(book, state)))
        last_state = state

    if current_day is not None and last_state is not None:
        result.daily_pnl[current_day] = _equity(book, last_state) - day_start_pnl

    result.trades = book.trades
    result.total_costs = book.total_costs
    return result


def _equity(book: PositionBook, state: MarketState | None) -> Decimal:
    if state is None:
        return book.realized_total - book.total_costs
    marks = {iid: q.mid for iid, q in state.quotes.items() if q.mid is not None}
    return book.net_pnl(marks)


def _execute(
    intent: OrderIntent,
    state: MarketState,
    book: PositionBook,
    result: BacktestResult,
    config: BacktestConfig,
) -> None:
    quote = state.quotes.get(intent.instrument_id)
    meta = state.meta.get(intent.instrument_id)
    if quote is None or meta is None:
        result.unfillable_orders += 1
        return
    fill = fill_price(quote, intent.side, config.scenario)
    if fill is None:
        result.unfillable_orders += 1
        return
    exchange = "BSE" if meta.underlying == "SENSEX" else "NSE"
    costs = option_trade_costs(intent.side, fill.price, intent.qty, exchange)
    book.apply_fill(
        state.ts, intent.instrument_id, intent.side, intent.qty, fill.price, costs.total
    )
