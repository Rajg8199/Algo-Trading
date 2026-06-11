"""Market-day heartbeats: a short INFO message proving the pipeline is alive,
with enough numbers that silence or weirdness is visible at a glance."""

from datetime import datetime, time

from sqlalchemy import text

from tp_core.models import Severity
from tp_core.timeutils import IST, now_ist
from tp_scheduler.context import JobContext

RECENT_COUNTS_SQL = text("""
    SELECT
      (SELECT count(*) FROM ticks WHERE ts > now() - interval '5 minutes') AS ticks_5m,
      (SELECT count(*) FROM option_chain WHERE ts > now() - interval '5 minutes') AS chain_5m
""")


async def run(ctx: JobContext) -> None:
    holidays = await ctx.events.holidays()
    today = now_ist().date()
    if today.weekday() >= 5 or today in holidays:
        return
    if not (time(9, 0) <= now_ist().time() <= time(15, 45)):
        return
    async with ctx.db.session() as s:
        result = await s.execute(RECENT_COUNTS_SQL)
        ticks_5m, chain_5m = result.one()
    db_ok = await ctx.db.ping()
    await ctx.alert(
        Severity.INFO,
        f"heartbeat_{datetime.now(IST).strftime('%H%M')}",
        f"❤️ recorder: {ticks_5m} ticks / {chain_5m} chain rows in last 5m · "
        f"db {'✓' if db_ok else '✗'}",
    )
