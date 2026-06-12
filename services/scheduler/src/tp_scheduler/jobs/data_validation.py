"""Nightly comprehensive data validation (Phase 2A). Supersedes the Phase 1
dq_sweep: runs the full tp_research validation framework, alerts on failures
(P1 if any P1 check failed), and pushes the daily quality report to Telegram."""

from datetime import date

from tp_research.validation.runner import run_validation

from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import now_ist
from tp_scheduler.context import JobContext

log = get_logger(__name__)


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    target = for_date or now_ist().date()
    holidays = await ctx.events.holidays()
    if target.weekday() >= 5 or target in holidays:
        log.info("validation_skipped_non_trading_day", date=target.isoformat())
        return

    report = await run_validation(ctx.db, target)

    if report.failures:
        worst = (
            Severity.P1 if any(f.severity is Severity.P1 for f in report.failures) else Severity.P2
        )
        lines = "\n".join(f"• {f.name}: {f.details}" for f in report.failures[:10])
        await ctx.alert(
            worst,
            f"dq_failures_{target.isoformat()}",
            f"Data quality {target}: {len(report.failures)} check(s) failed\n{lines}",
        )
    # Daily quality report goes to the INFO digest regardless of outcome.
    await ctx.alert(Severity.INFO, f"dq_report_{target.isoformat()}", report.summary_line())
