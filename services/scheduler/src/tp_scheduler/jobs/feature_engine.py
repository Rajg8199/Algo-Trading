"""Daily feature computation (Phase 2B). Runs after the close snapshot is in
(16:15 IST), after vol_metrics. Coverage below threshold raises a P2 — low
coverage usually means upstream data problems, not feature bugs."""

from datetime import date

from tp_research.features.engine import run_feature_engine

from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import now_ist
from tp_scheduler.context import JobContext

log = get_logger(__name__)

# Until ~1 year of IV history accumulates, percentile/rank/HAR features are
# legitimately None; 40% floor catches breakage without crying wolf early.
MIN_COVERAGE_PCT = 40.0


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    target = for_date or now_ist().date()
    holidays = await ctx.events.holidays()
    if target.weekday() >= 5 or target in holidays:
        return

    summary = await run_feature_engine(ctx.db, target)

    if summary.failed > 0:
        await ctx.alert(
            Severity.P2,
            "feature_engine_failures",
            f"Feature engine {target}: {summary.failed} feature(s) raised exceptions",
        )
    elif summary.coverage_pct < MIN_COVERAGE_PCT:
        await ctx.alert(
            Severity.P2,
            "feature_engine_coverage",
            f"Feature engine {target}: coverage {summary.coverage_pct:.0f}% "
            f"({summary.computed} computed / {summary.skipped} skipped)",
        )
    await ctx.alert(
        Severity.INFO,
        f"features_{target.isoformat()}",
        f"Features {target}: {summary.computed} computed, "
        f"{summary.skipped} skipped, coverage {summary.coverage_pct:.0f}%",
    )
