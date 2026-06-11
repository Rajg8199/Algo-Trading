"""Nightly data-quality sweep. Each check writes a dq_checks row; failures
raise a P2 alert. A trading day with no data is a P1 — that's lost research
data we can never buy back."""

from datetime import date, datetime, time

from sqlalchemy import text

from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import IST
from tp_scheduler.context import JobContext

log = get_logger(__name__)

# A full session at 60s cadence should produce well over this per underlying.
MIN_CHAIN_ROWS = 10_000
MIN_TICK_ROWS = 50_000

COUNT_SQL = text("""
    SELECT i.underlying, count(*) FROM {table} t
    JOIN instruments i USING (instrument_id)
    WHERE t.ts >= :day_start AND t.ts < :day_end AND i.underlying IN ('NIFTY','SENSEX')
    GROUP BY i.underlying
""")


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    target = for_date or date.today()  # noqa: DTZ011
    holidays = await ctx.events.holidays()
    if target.weekday() >= 5 or target in holidays:
        log.info("dq_sweep_skipped_non_trading_day", date=target.isoformat())
        return

    day_start = datetime.combine(target, time(9, 0), tzinfo=IST)
    day_end = datetime.combine(target, time(16, 0), tzinfo=IST)

    for table, minimum, severity in (
        ("option_chain", MIN_CHAIN_ROWS, Severity.P1),
        ("ticks", MIN_TICK_ROWS, Severity.P1),
    ):
        sql = text(str(COUNT_SQL).replace("{table}", table))
        async with ctx.db.session() as s:
            result = await s.execute(sql, {"day_start": day_start, "day_end": day_end})
            counts: dict[str, int] = dict(result.tuples().all())
        for underlying in ("NIFTY", "SENSEX"):
            count = counts.get(underlying, 0)
            passed = count >= minimum
            await ctx.ops.record_dq_check(
                target,
                f"{table}_volume_{underlying}",
                passed,
                {"rows": count, "minimum": minimum},
            )
            if not passed:
                await ctx.alert(
                    severity,
                    f"dq_{table}_{underlying}",
                    f"DQ FAIL {target}: {table}/{underlying} has {count} rows (min {minimum})",
                )
    log.info("dq_sweep_done", date=target.isoformat())
