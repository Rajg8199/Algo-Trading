"""Live intraday scalp scan -> Telegram, every 3 min during market hours.

Builds 3-min bars from the recorder's LIVE index spot ticks (NIFTY/SENSEX/
BANKNIFTY) and evaluates the EMA/RSI/ATR scalp signal on the last CLOSED bar.
Forward-test only — no intraday history exists to backtest — so every alert is
labelled UNVALIDATED. Index ticks are ~2-min cadence, so the bars are coarse.
"""

from datetime import date, time

from sqlalchemy import text
from tp_research.scalp import ScalpBar, ScalpParams, scalp_signal

from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import now_ist
from tp_scheduler.context import JobContext

log = get_logger(__name__)

UNDERLYINGS = ("NIFTY", "SENSEX", "BANKNIFTY")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
BAR = "3 minutes"

_BARS_SQL = text("""
    SELECT time_bucket(:bar, t.ts) AS b,
           first(t.ltp, t.ts) AS o, max(t.ltp) AS h, min(t.ltp) AS l, last(t.ltp, t.ts) AS c
    FROM ticks t JOIN instruments i USING (instrument_id)
    WHERE i.underlying = :u AND i.segment = 'INDEX'
      AND i.upstox_key NOT LIKE 'NSEBHAV%' AND t.ts > now() - interval '4 hours'
    GROUP BY b ORDER BY b
""")


def _format(underlying: str, sig: object) -> str:
    s = sig  # ScalpSignal
    return (
        f"🩳 Scalp · {underlying} · {s.ts:%H:%M}\n"  # type: ignore[attr-defined]
        f"{s.side} @ {s.price:,.1f}   stop {s.stop:,.1f}   tgt {s.target:,.1f}"  # type: ignore[attr-defined]
        f"   (RSI {s.rsi:.0f})\n\n"  # type: ignore[attr-defined]
        "⚠️ UNVALIDATED forward-test cue (index 3-min, ~2-min ticks — coarse). "
        "NOT a validated edge; scalping costs are brutal. Hard stop, small size."
    )


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    holidays = await ctx.events.holidays()
    now = now_ist()
    today = for_date or now.date()
    if today.weekday() >= 5 or today in holidays:
        return
    if not (MARKET_OPEN <= now.time() <= MARKET_CLOSE):
        return

    params = ScalpParams()
    for u in UNDERLYINGS:
        async with ctx.db.session() as s:
            rows = (await s.execute(_BARS_SQL, {"bar": BAR, "u": u})).all()
        if len(rows) < params.min_bars + 1:
            continue
        # drop the last (in-progress) bucket — evaluate the last CLOSED bar
        bars = [ScalpBar(r.b, float(r.o), float(r.h), float(r.l), float(r.c)) for r in rows[:-1]]
        sig = scalp_signal(bars, params)
        if sig is None:
            continue
        await ctx.alert(
            Severity.INFO,
            f"signal_scalp_{u}_{sig.side}_{sig.ts:%H%M}",
            _format(u, sig),
        )
        log.info("scalp_signal", underlying=u, side=sig.side, price=sig.price)
