"""Monte Carlo robustness analysis (3E) over a completed backtest's trade
PnL sequence. Seeded — same seed, same numbers, always.

Two resamplers:
- iid reshuffle: breaks all sequence structure (answers: was the equity
  curve's shape luck of ordering?)
- block bootstrap: preserves local clustering (vol regimes cluster losses;
  blocks keep that pain together instead of diluting it)
"""

from dataclasses import dataclass

import numpy as np

CONFIDENCE_LEVELS = (95.0, 99.0, 99.9)


@dataclass(frozen=True)
class MonteCarloReport:
    n_paths: int
    method: str
    # worst-tail percentiles of max drawdown across paths (rupees, positive)
    max_dd_p95: float
    max_dd_p99: float
    max_dd_p999: float
    # total-PnL confidence intervals (lower bound at each level)
    pnl_lower_p95: float
    pnl_lower_p99: float
    pnl_lower_p999: float
    prob_negative_pnl: float
    risk_of_ruin: float  # P(equity ever breaches -ruin_level)
    ruin_level: float

    def as_dict(self) -> dict[str, float | int | str]:
        return self.__dict__.copy()


def _max_drawdown(path: np.ndarray) -> float:
    equity = np.cumsum(path)
    peak = np.maximum.accumulate(np.concatenate(([0.0], equity)))[1:]
    return float(np.max(peak - equity, initial=0.0))


def _paths_iid(pnls: np.ndarray, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    idx = rng.integers(0, len(pnls), size=(n_paths, len(pnls)))
    return pnls[idx]


def _paths_block(
    pnls: np.ndarray, n_paths: int, block: int, rng: np.random.Generator
) -> np.ndarray:
    n = len(pnls)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, max(n - block, 1), size=(n_paths, n_blocks))
    out = np.empty((n_paths, n_blocks * block))
    for b in range(n_blocks):
        offsets = np.arange(block)
        out[:, b * block : (b + 1) * block] = pnls[np.minimum(starts[:, [b]] + offsets, n - 1)]
    return out[:, :n]


def monte_carlo(
    trade_pnls: list[float],
    method: str = "block",
    n_paths: int = 10_000,
    block_size: int = 5,
    ruin_level: float = 150_000.0,
    seed: int = 42,
) -> MonteCarloReport | None:
    """Returns None when there are too few trades to resample honestly —
    a Monte Carlo over 8 trades is theater, not analysis."""
    if len(trade_pnls) < 20:
        return None
    rng = np.random.default_rng(seed)
    pnls = np.asarray(trade_pnls, dtype=np.float64)

    if method == "iid":
        paths = _paths_iid(pnls, n_paths, rng)
    elif method == "block":
        paths = _paths_block(pnls, n_paths, block_size, rng)
    else:
        raise ValueError(f"unknown method: {method}")

    dds = np.apply_along_axis(_max_drawdown, 1, paths)
    totals = paths.sum(axis=1)
    equity = np.cumsum(paths, axis=1)
    ruined = (equity.min(axis=1) <= -ruin_level).mean()

    dd_p = {level: float(np.percentile(dds, level)) for level in CONFIDENCE_LEVELS}
    pnl_p = {level: float(np.percentile(totals, 100 - level)) for level in CONFIDENCE_LEVELS}

    return MonteCarloReport(
        n_paths=n_paths,
        method=method,
        max_dd_p95=dd_p[95.0],
        max_dd_p99=dd_p[99.0],
        max_dd_p999=dd_p[99.9],
        pnl_lower_p95=pnl_p[95.0],
        pnl_lower_p99=pnl_p[99.0],
        pnl_lower_p999=pnl_p[99.9],
        prob_negative_pnl=float((totals < 0).mean()),
        risk_of_ruin=float(ruined),
        ruin_level=ruin_level,
    )
