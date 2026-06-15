"""Backtest short-term mean-reversion (H-MR-01) with walk-forward stability.

    uv run python scripts/meanrev_backtest.py [--min-turnover-cr 5]

Host runs need POSTGRES_HOST=localhost.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from tp_research.equity.importer import filter_liquid, load_recent_bars, universe
from tp_research.screener.backtest import period_breakdown
from tp_research.screener.meanrev import MeanRevParams, backtest_meanrev

from tp_core.config import get_settings
from tp_core.db import Database


def _p(msg: str) -> None:
    print(msg, flush=True)  # noqa: T201 — ops CLI


def _f(v: float | None, d: int = 2) -> str:
    return "—" if v is None else f"{v:.{d}f}"


async def main() -> int:
    ap = argparse.ArgumentParser(description="Mean-reversion backtest (H-MR-01)")
    ap.add_argument("--min-turnover-cr", type=float, default=5.0)
    ap.add_argument("--lookback", type=int, default=900)
    args = ap.parse_args()

    params = MeanRevParams()
    db = Database(get_settings())
    try:
        syms = await universe(db, min_days=params.min_history)
        bars = await load_recent_bars(db, symbols=syms, lookback_per_symbol=args.lookback)
        liq = filter_liquid(bars, args.min_turnover_cr)
        _p(f"liquid universe (split-adjusted): {len(liq)} symbols")

        trades, res = backtest_meanrev(dict(liq), params)
        _p("")
        _p("=== MEAN-REVERSION (RSI2 dip in uptrend), EXPECTED costs ===")
        win = None if res.win_rate is None else res.win_rate * 100
        _p(f"  trades         {res.n_trades}  (W {res.wins} / L {res.losses})")
        _p(f"  win rate       {_f(win, 1)}%")
        _p(f"  expectancy     {_f(res.expectancy_r)} R per trade")
        _p(f"  profit factor  {_f(res.profit_factor)}")
        _p(f"  avg win/loss   {_f(res.avg_win_r)}R / {_f(res.avg_loss_r)}R")
        _p(f"  max drawdown   {_f(res.max_drawdown_pct, 1)}%")
        _p(f"  total return   {_f(res.total_return_pct, 1)}%")
        _p(f"  avg hold       {_f(res.avg_holding_days, 1)} days")

        _p("")
        _p("  walk-forward (3 calendar periods):")
        parts = period_breakdown(trades, params, n_periods=3)
        all_pos = True
        for label, pres in parts:
            exp = pres.expectancy_r
            all_pos = all_pos and exp is not None and exp > 0
            _p(
                f"    {label}:  {pres.n_trades:>4} trades  "
                f"exp {_f(exp)}R  PF {_f(pres.profit_factor)}"
            )

        gate_core = res.acceptable
        _p("")
        verdict = "PASS ✓ — PROMISING" if (gate_core and all_pos) else "FAIL ✗ — UNVALIDATED"
        _p(f"  ACCEPTANCE GATE: {verdict}")
        _p(f"  (core gate {'pass' if gate_core else 'fail'}, walk-forward all-positive {all_pos})")
    finally:
        await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
