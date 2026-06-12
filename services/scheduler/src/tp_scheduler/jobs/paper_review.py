"""Daily paper-trading review (16:30 IST).

Analytics are deterministic SQL; the optional LLM narrative (Claude, via raw
API call iff ANTHROPIC_API_KEY is set) only REPHRASES computed numbers — it
never computes, and its absence degrades gracefully to analytics-only.

Learning layer contract: recommendations are drawn ONLY from the registered
Experiment-001 grid, carry requires_approval=true, and are applied by a human
editing datalake/paper/params.json. Nothing self-deploys. With fewer than 30
closed trades the layer says exactly that and recommends nothing.
"""

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from tp_core.models import Severity
from tp_core.timeutils import now_ist
from tp_scheduler.context import JobContext

REGISTERED_GRID = {
    "min_vrp_points": [1.0, 2.0, 3.0],
    "min_iv_percentile": [70.0, 80.0, 90.0],
    "max_vov": [1.0, 1.5],
    "stop_mult": [1.5, 2.0],
}
MIN_TRADES_FOR_SUGGESTIONS = 30

_STATS_SQL = text("""
    SELECT
      (SELECT coalesce(sum(net_pnl), 0) FROM pnl_daily
        WHERE mode='PAPER' AND trade_date = :today) AS today_pnl,
      (SELECT coalesce(sum(net_pnl), 0) FROM pnl_daily WHERE mode='PAPER') AS total_pnl,
      (SELECT count(*) FROM pnl_daily WHERE mode='PAPER' AND net_pnl > 0) AS up_days,
      (SELECT count(*) FROM pnl_daily WHERE mode='PAPER') AS total_days,
      (SELECT count(*) FROM orders WHERE mode='PAPER') AS total_orders,
      (SELECT count(*) FROM orders WHERE mode='PAPER'
        AND signal_snapshot->>'reason' = 'stop') AS stop_orders,
      (SELECT round(avg(slippage)::numeric, 2) FROM fills f
        JOIN orders o USING (order_id) WHERE o.mode='PAPER') AS avg_slippage
""")

_LEADERBOARD_SQL = text("""
    SELECT strategy, sum(net_pnl) AS pnl, count(*) AS days
    FROM pnl_daily WHERE mode='PAPER' GROUP BY strategy ORDER BY pnl DESC
""")


async def _llm_narrative(stats: dict[str, Any]) -> str | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    prompt = (
        "You are reviewing one day of PAPER trading for an UNVALIDATED options "
        "strategy. Write <=80 words: what the numbers say, one risk to watch. "
        "Do not invent numbers; do not recommend parameter values.\n"
        f"Stats: {json.dumps(stats, default=str)}"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        response.raise_for_status()
        return str(response.json()["content"][0]["text"]).strip()
    except Exception:
        return None  # narrative is optional by design


def _suggestions(stats: dict[str, Any]) -> list[dict[str, Any]]:
    if int(stats["total_orders"]) < MIN_TRADES_FOR_SUGGESTIONS:
        return [
            {
                "type": "no_action",
                "detail": f"only {stats['total_orders']} orders; "
                f"suggestions begin at {MIN_TRADES_FOR_SUGGESTIONS}",
                "requires_approval": True,
            }
        ]
    out: list[dict[str, Any]] = []
    orders = max(int(stats["total_orders"]), 1)
    stop_ratio = int(stats["stop_orders"]) / orders
    if stop_ratio > 0.4:
        out.append(
            {
                "type": "parameter",
                "parameter": "stop_mult",
                "candidates": REGISTERED_GRID["stop_mult"],
                "detail": f"stop-out ratio {stop_ratio:.0%} > 40% — consider the wider "
                "registered stop; evaluate on next 30 trades before judging",
                "requires_approval": True,
            }
        )
    if not out:
        out.append({"type": "no_action", "detail": "no rule triggered", "requires_approval": True})
    return out


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    target = for_date or now_ist().date()
    holidays = await ctx.events.holidays()
    if target.weekday() >= 5 or target in holidays:
        return

    async with ctx.db.session() as s:
        row = (await s.execute(_STATS_SQL, {"today": target})).one()
        leaderboard = [
            {"strategy": r.strategy, "pnl": float(r.pnl), "days": r.days}
            for r in (await s.execute(_LEADERBOARD_SQL)).all()
        ]

    stats = {
        "date": str(target),
        "today_net_pnl": float(row.today_pnl),
        "total_net_pnl": float(row.total_pnl),
        "day_win_rate": (row.up_days / row.total_days) if row.total_days else None,
        "total_orders": int(row.total_orders),
        "stop_orders": int(row.stop_orders),
        "avg_slippage": float(row.avg_slippage) if row.avg_slippage is not None else None,
        "leaderboard": leaderboard,
    }
    suggestions = _suggestions(stats)
    narrative = await _llm_narrative(stats)

    review = {"stats": stats, "suggestions": suggestions, "narrative": narrative}
    out = Path(ctx.settings.datalake_root) / "paper" / "reviews"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{target}.json").write_text(json.dumps(review, indent=2))

    wr = f"{stats['day_win_rate']:.0%}" if stats["day_win_rate"] is not None else "—"
    lines = [
        f"🧪 Paper review {target}",
        f"Today: ₹{stats['today_net_pnl']:,.0f} · Total: ₹{stats['total_net_pnl']:,.0f}",
        f"Day win rate: {wr} · Orders: {stats['total_orders']} "
        f"(stops {stats['stop_orders']}) · Avg slip: {stats['avg_slippage']}",
        "Suggestions (approval required, registered grid only):",
        *[f"  • {s['detail']}" for s in suggestions],
    ]
    if narrative:
        lines.append(f"AI note: {narrative}")
    await ctx.alert(Severity.INFO, f"paper_review_{target}", "\n".join(lines))
