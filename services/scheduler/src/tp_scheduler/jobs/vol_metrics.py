"""Daily vol metrics from recorded data.

Computes what recorded data supports today: close-close RV, intraday/overnight
split, India VIX level + 1y percentile. IV-derived fields (ATM IV, term slope,
skew, VRP) are populated by the chain-analytics job added with the research
phase — the columns exist and stay NULL until then, never silently faked.
"""

import math
from datetime import date, timedelta

from sqlalchemy import text

from tp_core.telemetry.logging import get_logger
from tp_scheduler.context import JobContext

log = get_logger(__name__)

DAILY_OHLC_SQL = text("""
    SELECT time_bucket('1 day', ts) AS day,
           first(ltp, ts) AS open, last(ltp, ts) AS close
    FROM ticks t
    JOIN instruments i USING (instrument_id)
    WHERE i.underlying = :underlying AND i.segment = 'INDEX'
      AND ts >= :start
    GROUP BY day ORDER BY day
""")

ANNUALIZATION = math.sqrt(252)


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    target = for_date or date.today()  # noqa: DTZ011
    for underlying in ("NIFTY", "SENSEX"):
        await _compute_one(ctx, underlying, target)
    await _compute_vix(ctx, target)


async def _compute_one(ctx: JobContext, underlying: str, target: date) -> None:
    start = target - timedelta(days=60)
    async with ctx.db.session() as s:
        result = await s.execute(DAILY_OHLC_SQL, {"underlying": underlying, "start": start})
        days = [(d, float(o), float(c)) for d, o, c in result.all() if o and c]
    if len(days) < 21:
        log.info("vol_metrics_insufficient_history", underlying=underlying, days=len(days))
        return

    closes = [c for _, _, c in days]
    opens = [o for _, o, _ in days]
    cc = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    overnight = [math.log(opens[i] / closes[i - 1]) for i in range(1, len(closes))]
    intraday = [math.log(closes[i] / opens[i]) for i in range(1, len(closes))]

    def ann_vol(returns: list[float], window: int = 20) -> float:
        tail = returns[-window:]
        mean = sum(tail) / len(tail)
        var = sum((r - mean) ** 2 for r in tail) / (len(tail) - 1)
        return math.sqrt(var) * ANNUALIZATION * 100

    await ctx.vol_metrics.upsert(
        {
            "trade_date": target,
            "underlying": underlying,
            "rv_cc_20d": ann_vol(cc),
            "rv_intraday": ann_vol(intraday),
            "rv_overnight": ann_vol(overnight),
        }
    )
    log.info("vol_metrics_computed", underlying=underlying, rv_cc_20d=round(ann_vol(cc), 2))


async def _compute_vix(ctx: JobContext, target: date) -> None:
    async with ctx.db.session() as s:
        result = await s.execute(
            DAILY_OHLC_SQL, {"underlying": "INDIAVIX", "start": target - timedelta(days=400)}
        )
        days = [(d, float(c)) for d, _o, c in result.all() if c]
    if not days:
        return
    closes = [c for _, c in days]
    latest = closes[-1]
    percentile = 100.0 * sum(1 for c in closes if c <= latest) / len(closes)
    for underlying in ("NIFTY", "SENSEX"):
        await ctx.vol_metrics.upsert(
            {
                "trade_date": target,
                "underlying": underlying,
                "india_vix": latest,
                "vix_percentile_1y": percentile,
            }
        )
