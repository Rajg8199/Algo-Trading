"""Telegram message formatting for the breakout scanner.

Honesty is structural here: unless a strategy has cleared its backtest gate,
every message leads with an UNVALIDATED banner and never frames a signal as a
recommendation. Per the screens in docs/research/, the breakout has NO proven
edge — so `validated` is False and these go out as a watchlist, not advice.
"""

from __future__ import annotations

from datetime import date

from tp_research.screener.models import BreakoutSignal

_UNVALIDATED_BANNER = (
    "⚠️ UNVALIDATED — these are rule matches, NOT recommendations. The backtest "
    "shows no proven edge (negative expectancy). For watching only. Never risk "
    "more than you can lose; size for being wrong."
)


def format_breakout_alert(
    signals: list[BreakoutSignal],
    as_of: date,
    *,
    validated: bool,
    capital: float = 1_000_000.0,
    risk_pct: float = 0.01,
    limit: int = 15,
) -> str:
    """One Telegram-ready message. Always labels validation status; lists each
    candidate with its objective entry / ATR-stop / target and a risk-sized qty."""
    header = f"📈 Breakout scan · {as_of:%d %b %Y}"
    if not signals:
        body = "No breakouts today. (Most days produce none — that is the filter working.)"
        banner = "" if validated else f"\n\n{_UNVALIDATED_BANNER}"
        return f"{header}\n\n{body}{banner}"

    lines = []
    for s in signals[:limit]:
        tkr = s.symbol.replace("NSE:", "")
        qty = s.position_size(capital, risk_pct)
        tgt = "trail" if s.target is None else f"{s.target:.1f}"
        lines.append(
            f"• {tkr}  entry {s.entry:.1f}  stop {s.stop:.1f}  tgt {tgt}  "
            f"vol {s.volume_ratio:.1f}x  ~{qty} sh"
        )
    extra = f"\n…and {len(signals) - limit} more" if len(signals) > limit else ""
    status = "✅ VALIDATED strategy" if validated else _UNVALIDATED_BANNER
    sizing = f"(sizing: {risk_pct:.0%} risk on ₹{capital:,.0f})"
    top = f"{header} · {len(signals)} candidates\n\n"
    return top + "\n".join(lines) + extra + f"\n\n{status}\n{sizing}"
