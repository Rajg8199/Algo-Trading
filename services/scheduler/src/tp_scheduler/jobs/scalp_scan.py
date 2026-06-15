"""Live intraday scalp scan -> Telegram, every 3 min during market hours.

Builds 3-min AND 5-min bars from the recorder's LIVE index spot ticks
(NIFTY/SENSEX/BANKNIFTY) and evaluates the EMA/RSI/ATR scalp signal on the last
CLOSED bar of each. Forward-test only (no intraday history to backtest) — every
alert is labelled UNVALIDATED. Skips the noisy open/close; only emits FRESH
signals (not trend continuations) to avoid over-trading.
"""

from datetime import date, time

from sqlalchemy import text
from tp_research.scalp import ScalpBar, ScalpParams, ScalpSignal, scalp_signal

from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import now_ist
from tp_scheduler.context import JobContext

log = get_logger(__name__)

UNDERLYINGS = ("NIFTY", "SENSEX", "BANKNIFTY")
TIMEFRAMES = ("3 minutes", "5 minutes")
# Skip the opening auction spike and the pre-close — worst slippage for scalps.
TRADE_OPEN = time(9, 30)
TRADE_CLOSE = time(15, 20)

_BARS_SQL = text("""
    SELECT time_bucket(:bar, t.ts) AS b,
           first(t.ltp, t.ts) AS o, max(t.ltp) AS h, min(t.ltp) AS l, last(t.ltp, t.ts) AS c
    FROM ticks t JOIN instruments i USING (instrument_id)
    WHERE i.underlying = :u AND i.segment = 'INDEX'
      AND i.upstox_key NOT LIKE 'NSEBHAV%' AND t.ts > now() - interval '6 hours'
    GROUP BY b ORDER BY b
""")


def _format(underlying: str, tf: str, sig: ScalpSignal) -> str:
    return (
        f"🩳 Scalp · {underlying} · {tf.split()[0]}m · {sig.ts:%H:%M}\n"
        f"{sig.side} @ {sig.price:,.1f}   stop {sig.stop:,.1f}   tgt {sig.target:,.1f}"
        f"   (RSI {sig.rsi:.0f})\n\n"
        "⚠️ UNVALIDATED forward-test cue (index spot, coarse ~2-min ticks). "
        "NOT a validated edge; scalping costs are brutal. Hard stop, small size."
    )


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    holidays = await ctx.events.holidays()
    now = now_ist()
    today = for_date or now.date()
    if today.weekday() >= 5 or today in holidays:
        return
    if not (TRADE_OPEN <= now.time() <= TRADE_CLOSE):
        return

    params = ScalpParams()
    for u in UNDERLYINGS:
        for tf in TIMEFRAMES:
            async with ctx.db.session() as s:
                rows = (await s.execute(_BARS_SQL, {"bar": tf, "u": u})).all()
            if len(rows) < params.min_bars + 2:
                continue
            # drop the in-progress bucket; evaluate the last CLOSED bar
            bars = [
                ScalpBar(r.b, float(r.o), float(r.h), float(r.l), float(r.c)) for r in rows[:-1]
            ]
            sig = scalp_signal(bars, params)
            if sig is None:
                continue
            # only FRESH signals: skip if the prior closed bar already fired the
            # same side (a trend continuation, not a new setup)
            prev = scalp_signal(bars[:-1], params)
            if prev is not None and prev.side == sig.side:
                continue
            await ctx.alert(
                Severity.INFO,
                f"signal_scalp_{u}_{tf.split()[0]}m_{sig.side}_{sig.ts:%H%M}",
                _format(u, tf, sig),
            )
            log.info("scalp_signal", underlying=u, tf=tf, side=sig.side, price=sig.price)
