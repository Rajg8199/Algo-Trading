"""Backtest the swing breakout strategy on real ingested NSE equity history.

This is the honesty gate: it prints whatever the rules actually produce —
expectancy, profit factor, drawdown — and whether that clears the acceptance
gate. A passing result is what (later) lets the Signals page show VALIDATED.

    uv run python scripts/breakout_backtest.py
    uv run python scripts/breakout_backtest.py --min-turnover-cr 10 --target-r 2

Host runs need POSTGRES_HOST=localhost.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import date

from tp_research.equity.importer import load_recent_bars, universe
from tp_research.screener import BreakoutParams, DailyBar, backtest_breakout, scan

from tp_core.config import get_settings
from tp_core.db import Database


def _p(msg: str) -> None:
    print(msg, flush=True)  # noqa: T201 — ops CLI


def _f(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def market_regime(bars_by_symbol: dict[str, Sequence[DailyBar]], sma: int = 200) -> frozenset[date]:
    """Self-contained market-trend filter: build an equal-weight daily-return
    index from the universe, then allow entries only on dates where that index
    is above its own `sma`-day average (broad market in an uptrend). No external
    index data needed."""
    dates = sorted({b.day for hist in bars_by_symbol.values() for b in hist})
    closes = {sym: {b.day: b.close for b in hist} for sym, hist in bars_by_symbol.items()}
    levels: list[tuple[date, float]] = []
    level = 1.0
    prev: date | None = None
    for d in dates:
        if prev is not None:
            rets = [
                dc[d] / dc[prev] - 1.0
                for dc in closes.values()
                if d in dc and prev in dc and dc[prev] > 0
            ]
            if rets:
                level *= 1.0 + sum(rets) / len(rets)
        levels.append((d, level))
        prev = d
    vals = [lv for _, lv in levels]
    allowed = {
        d
        for i, (d, lv) in enumerate(levels)
        if i + 1 >= sma and lv > sum(vals[i + 1 - sma : i + 1]) / sma
    }
    return frozenset(allowed)


def _liquid(
    bars_by_symbol: dict[str, list[DailyBar]], min_turnover_cr: float
) -> dict[str, Sequence[DailyBar]]:
    """Keep symbols whose median daily turnover (close x volume) over the last
    ~120 days clears the floor — tradeable names only, no microcap noise."""
    floor = min_turnover_cr * 1e7  # 1 crore = 1e7 rupees
    out: dict[str, Sequence[DailyBar]] = {}
    for sym, hist in bars_by_symbol.items():
        if len(hist) < 120:
            continue
        turn = sorted(b.close * b.volume for b in hist[-120:])
        if turn[len(turn) // 2] >= floor:
            out[sym] = hist
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description="Swing breakout backtest on ingested equity bars")
    ap.add_argument("--min-turnover-cr", type=float, default=5.0, help="liquidity floor, cr/day")
    ap.add_argument("--lookback", type=int, default=900, help="bars per symbol to load")
    ap.add_argument("--target-r", type=float, default=None, help="fixed take-profit in R")
    ap.add_argument("--breakout-lookback", type=int, default=20, help="Donchian high window")
    ap.add_argument("--regime", action="store_true", help="gate entries on market uptrend")
    args = ap.parse_args()

    params = BreakoutParams(target_r=args.target_r, breakout_lookback=args.breakout_lookback)
    db = Database(get_settings())
    try:
        syms = await universe(db, min_days=params.min_history)
        _p(f"universe (>= {params.min_history} days history): {len(syms)} symbols")
        if not syms:
            _p("No symbols with enough history yet — run the backfill first.")
            return 1
        bars = await load_recent_bars(db, symbols=syms, lookback_per_symbol=args.lookback)
        liq = _liquid(bars, args.min_turnover_cr)
        _p(f"liquid (median 120d turnover >= ₹{args.min_turnover_cr:g} cr): {len(liq)} symbols")

        allowed = None
        if args.regime:
            allowed = market_regime(dict(liq))
            total_days = len({b.day for hist in liq.values() for b in hist})
            _p(f"regime filter ON: market in uptrend on {len(allowed)}/{total_days} days")

        res = backtest_breakout(dict(liq), params, entry_allowed=allowed)
        _p("")
        cfg = f"breakout={args.breakout_lookback}d target_r={args.target_r} regime={args.regime}"
        _p(f"=== BACKTEST — swing breakout, EXPECTED costs ({cfg}) ===")
        win = None if res.win_rate is None else res.win_rate * 100
        _p(f"  trades         {res.n_trades}  (W {res.wins} / L {res.losses})")
        _p(f"  win rate       {_f(win, 1)}%")
        _p(f"  expectancy     {_f(res.expectancy_r)} R per trade")
        _p(f"  profit factor  {_f(res.profit_factor)}")
        _p(f"  avg win/loss   {_f(res.avg_win_r)}R / {_f(res.avg_loss_r)}R")
        _p(f"  max drawdown   {_f(res.max_drawdown_pct, 1)}%   (1% risk/trade, fixed-fractional)")
        _p(f"  total return   {_f(res.total_return_pct, 1)}%")
        _p(f"  avg hold       {_f(res.avg_holding_days, 1)} days")
        _p("")
        _p(f"  ACCEPTANCE GATE: {'PASS ✓' if res.acceptable else 'FAIL ✗ — stays UNVALIDATED'}")
        _p("  (gate: >=30 trades, expectancy >0.1R, PF >1.3, maxDD <25%)")

        today = scan(dict(liq), params)
        _p("")
        _p(f"=== today's breakout candidates: {len(today)} ===")
        for s in today[:25]:
            tgt = "trail" if s.target is None else f"{s.target:.1f}"
            _p(
                f"  {s.symbol:<18} entry {s.entry:8.1f}  stop {s.stop:8.1f}  "
                f"tgt {tgt:>8}  vol {s.volume_ratio:.1f}x"
            )
    finally:
        await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
