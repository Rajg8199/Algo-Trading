"""Backtest cross-sectional 12-1 momentum (H-MOM-01) on ingested NSE history.

    uv run python scripts/momentum_backtest.py
    uv run python scripts/momentum_backtest.py --min-turnover-cr 10 --no-regime

Host runs need POSTGRES_HOST=localhost.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from tp_research.equity.importer import load_recent_bars, universe
from tp_research.screener import DailyBar, MomentumParams, backtest_momentum, current_picks

from tp_core.config import get_settings
from tp_core.db import Database


def _p(msg: str) -> None:
    print(msg, flush=True)  # noqa: T201 — ops CLI


def _liquid(
    bars_by_symbol: dict[str, list[DailyBar]], min_turnover_cr: float
) -> dict[str, Sequence[DailyBar]]:
    floor = min_turnover_cr * 1e7
    out: dict[str, Sequence[DailyBar]] = {}
    for sym, hist in bars_by_symbol.items():
        if len(hist) < 120:
            continue
        turn = sorted(b.close * b.volume for b in hist[-120:])
        if turn[len(turn) // 2] >= floor:
            out[sym] = hist
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-sectional momentum backtest (H-MOM-01)")
    ap.add_argument("--min-turnover-cr", type=float, default=5.0)
    ap.add_argument("--lookback", type=int, default=900)
    ap.add_argument("--no-regime", action="store_true", help="disable the market-trend overlay")
    args = ap.parse_args()

    params = MomentumParams(use_regime=not args.no_regime)
    db = Database(get_settings())
    try:
        syms = await universe(db, min_days=params.min_history)
        _p(f"universe (>= {params.min_history} days history): {len(syms)} symbols")
        if not syms:
            _p("No symbols with enough history — run the backfill first.")
            return 1
        bars = await load_recent_bars(db, symbols=syms, lookback_per_symbol=args.lookback)
        liq = _liquid(bars, args.min_turnover_cr)
        _p(f"liquid (median 120d turnover >= ₹{args.min_turnover_cr:g} cr): {len(liq)} symbols")

        res = backtest_momentum(dict(liq), params)
        _p("")
        _p(f"=== MOMENTUM 12-1 — monthly, regime={'on' if params.use_regime else 'off'} ===")
        _p(f"  rebalances       {res.n_rebalances}")
        _p(
            f"  ann return       {res.ann_return_pct:.1f}%   "
            f"(benchmark {res.benchmark_ann_return_pct:.1f}%)"
        )
        _p(f"  excess vs bench  {res.excess_ann_pct:+.1f}% / yr")
        _p(f"  ann volatility   {res.ann_vol_pct:.1f}%")
        _p(f"  Sharpe           {res.sharpe:.2f}")
        _p(f"  max drawdown     {res.max_drawdown_pct:.1f}%")
        _p(f"  hit rate         {res.hit_rate * 100:.0f}% of months positive")
        _p(f"  total return     {res.total_return_pct:.1f}%")
        _p("")
        verdict = "PASS ✓ — PROMISING" if res.acceptable else "FAIL ✗ — UNVALIDATED"
        _p(f"  ACCEPTANCE GATE: {verdict}")
        _p("  (gate: >=18 rebalances, ann_return > benchmark, Sharpe > 0.8, maxDD < 35%)")

        held, risk_on = current_picks(dict(liq), params)
        _p("")
        _p(f"=== today's momentum book: {'RISK-ON' if risk_on else 'CASH (market < 200DMA)'} ===")
        _p("  " + (", ".join(s.replace("NSE:", "") for s in held) if held else "(flat)"))
    finally:
        await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
