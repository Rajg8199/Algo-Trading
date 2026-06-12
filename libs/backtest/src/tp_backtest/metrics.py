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


def metrics_from_series(
    daily_pnl: list[float],
    trade_pnl_list: list[float],
    capital: float,
    total_costs: float,
    unfillable_orders: int,
) -> Metrics:
    """Metrics over concatenated walk-forward validation segments, where no
    single BacktestResult exists."""
    daily = np.asarray(daily_pnl, dtype=np.float64)
    sharpe = None
    if len(daily) >= 20 and capital > 0:
        returns = daily / capital
        std = float(np.std(returns, ddof=1))
        if std > 1e-12:
            sharpe = float(np.mean(returns) / std * math.sqrt(TRADING_DAYS))

    wins = [p for p in trade_pnl_list if p > 0]
    losses = [p for p in trade_pnl_list if p < 0]
    equity = np.cumsum(daily) if len(daily) else np.array([0.0])
    peak = np.maximum.accumulate(np.concatenate(([0.0], equity)))[1:]
    max_dd = float(np.max(peak - equity, initial=0.0))

    return Metrics(
        net_pnl=float(np.sum(daily)),
        sharpe=sharpe,
        profit_factor=(sum(wins) / abs(sum(losses))) if wins and losses else None,
        expectancy=(sum(trade_pnl_list) / len(trade_pnl_list)) if trade_pnl_list else None,
        max_drawdown=max_dd,
        max_drawdown_pct=100.0 * max_dd / capital if capital else 0.0,
        win_rate=(len(wins) / len(trade_pnl_list)) if trade_pnl_list else None,
        n_trades=len(trade_pnl_list),
        n_days=len(daily),
        total_costs=total_costs,
        unfillable_orders=unfillable_orders,
    )


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Acklam's rational approximation to the inverse normal CDF (|err|<1e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0,1)")
    a = (
        -39.69683028665376,
        220.9460984245205,
        -275.9285104469687,
        138.3577518672690,
        -30.66479806614716,
        2.506628277459239,
    )
    b = (
        -54.47609879822406,
        161.5858368580409,
        -155.6989798598866,
        66.80131188771972,
        -13.28068155288572,
    )
    c = (
        -0.007784894002430293,
        -0.3223964580411365,
        -2.400758277161838,
        -2.549732539343734,
        4.374664141464968,
        2.938163982698783,
    )
    d = (0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416)
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > p_high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def deflated_sharpe(
    observed_sharpe_annual: float,
    n_days: int,
    n_trials: int,
    daily_returns: np.ndarray | None = None,
) -> float | None:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014): probability the
    observed Sharpe exceeds the expected max Sharpe of n_trials of noise.

    Returns P in [0,1]; ≥0.90 required by experiment 001. None if the sample
    is too small to say anything."""
    if n_days < 30 or n_trials < 1:
        return None
    sr_daily = observed_sharpe_annual / math.sqrt(TRADING_DAYS)

    skew, kurt = 0.0, 3.0
    if daily_returns is not None and len(daily_returns) >= 30:
        std = float(np.std(daily_returns, ddof=1))
        if std > 1e-12:
            z = (daily_returns - float(np.mean(daily_returns))) / std
            skew = float(np.mean(z**3))
            kurt = float(np.mean(z**4))

    euler_gamma = 0.5772156649015329
    if n_trials == 1:
        sr_benchmark = 0.0
    else:
        e = math.e
        sr_benchmark = math.sqrt(1.0 / n_days) * (
            (1 - euler_gamma) * _norm_ppf(1 - 1.0 / n_trials)
            + euler_gamma * _norm_ppf(1 - 1.0 / (n_trials * e))
        )

    denom = 1 - skew * sr_daily + ((kurt - 1) / 4.0) * sr_daily**2
    if denom <= 0:
        return None
    z_stat = (sr_daily - sr_benchmark) * math.sqrt(n_days - 1) / math.sqrt(denom)
    return _norm_cdf(z_stat)
