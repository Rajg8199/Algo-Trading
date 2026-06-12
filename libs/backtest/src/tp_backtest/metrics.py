"""Performance metrics over a BacktestResult. All ratios computed on NET
numbers (after costs) — gross metrics are not reported anywhere, by policy."""

import math
from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from tp_backtest.engine import BacktestResult

TRADING_DAYS = 252


@dataclass(frozen=True)
class Metrics:
    net_pnl: float
    sharpe: float | None
    profit_factor: float | None
    expectancy: float | None  # mean net PnL per completed trade
    max_drawdown: float  # rupees, positive number
    max_drawdown_pct: float  # % of capital
    win_rate: float | None
    n_trades: int  # completed (CLOSE/SETTLE) trade events
    n_days: int
    total_costs: float
    unfillable_orders: int

    def as_dict(self) -> dict[str, float | int | None]:
        return self.__dict__.copy()


def trade_pnls(result: BacktestResult) -> list[float]:
    """Net PnL per completed trade event: realized PnL minus the full cost
    stack allocated evenly across completed trades (open-leg costs belong to
    the round trip they opened; even allocation is the unbiased approximation
    given legs can close at different times)."""
    completed = [t for t in result.trades if t.tag in ("CLOSE", "SETTLE")]
    if not completed:
        return []
    cost_share = float(result.total_costs) / len(completed)
    return [float(t.realized_pnl) - cost_share for t in completed]


def compute_metrics(result: BacktestResult) -> Metrics:
    capital = float(result.config.capital)
    daily = np.array([float(v) for v in result.daily_pnl.values()], dtype=np.float64)
    n_days = len(daily)

    sharpe = None
    if n_days >= 20 and capital > 0:
        returns = daily / capital
        std = float(np.std(returns, ddof=1))
        if std > 1e-12:
            sharpe = float(np.mean(returns) / std * math.sqrt(TRADING_DAYS))

    pnls = trade_pnls(result)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and wins else None
    expectancy = (sum(pnls) / len(pnls)) if pnls else None
    win_rate = (len(wins) / len(pnls)) if pnls else None

    equity = np.array([float(v) for _, v in result.equity_curve], dtype=np.float64)
    if len(equity):
        peak = np.maximum.accumulate(equity)
        dd = peak - equity
        max_dd = float(np.max(dd))
    else:
        max_dd = 0.0

    return Metrics(
        net_pnl=float(result.final_pnl),
        sharpe=sharpe,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown=max_dd,
        max_drawdown_pct=100.0 * max_dd / capital if capital else 0.0,
        win_rate=win_rate,
        n_trades=len(pnls),
        n_days=n_days,
        total_costs=float(result.total_costs),
        unfillable_orders=result.unfillable_orders,
    )


def equity_from_decimal(values: list[Decimal]) -> np.ndarray:
    return np.array([float(v) for v in values], dtype=np.float64)
