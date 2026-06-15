"""Intraday LIVE index-options snapshot -> Telegram, during market hours.

Computes spot / ATM IV / ATM straddle / PCR from the recorder's latest chain
snapshot plus live India VIX, every ~30 min while the market is open. Factual
monitoring — informational only, never a buy/sell. Skips off-hours/holidays."""

from datetime import date, time

from tp_research.options import (
    OPTIONS_UNDERLYINGS,
    LiveOptionsSnapshot,
    format_live_options,
    load_india_vix,
    load_live_snapshot,
)

from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import now_ist
from tp_scheduler.context import JobContext

log = get_logger(__name__)

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    holidays = await ctx.events.holidays()
    now = now_ist()
    today = for_date or now.date()
    if today.weekday() >= 5 or today in holidays:
        return
    if not (MARKET_OPEN <= now.time() <= MARKET_CLOSE):
        return

    snapshots: dict[str, LiveOptionsSnapshot | None] = {}
    for name in OPTIONS_UNDERLYINGS:
        snapshots[name] = await load_live_snapshot(ctx.db, name)
    vix = await load_india_vix(ctx.db)

    have = [n for n, s in snapshots.items() if s is not None]
    message = format_live_options(snapshots, vix, now)
    await ctx.alert(Severity.INFO, f"signal_options_live_{now:%H%M}", message)
    log.info("options_live_sent", time=now.strftime("%H:%M"), with_data=have, vix=vix)
