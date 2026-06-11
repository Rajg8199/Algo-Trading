"""Daily instrument-master refresh: download, parse our universe, upsert."""

from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_scheduler.context import JobContext
from tp_upstox.rest import download_instrument_master

log = get_logger(__name__)


async def run(ctx: JobContext) -> None:
    instruments = await download_instrument_master()
    if len(instruments) < 100:
        await ctx.alert(
            Severity.P2,
            "instrument_master_thin",
            f"Instrument master parse produced only {len(instruments)} rows — investigate",
        )
        return
    count = await ctx.instruments.upsert_many(instruments)
    log.info("instruments_refreshed", count=count)
