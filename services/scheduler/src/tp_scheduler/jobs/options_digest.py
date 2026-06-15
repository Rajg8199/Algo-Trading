"""EOD index-options market-structure digest -> Telegram.

Reads the latest feature-store values per index (ATM IV, IV percentile/rank,
term slope, skew, vov, realized vol/VRP, OI) and sends one factual snapshot.
Informational only — there is no validated options edge, so this never frames a
buy/sell. Runs after the feature engine (16:15)."""

from datetime import date

from tp_research.options import OPTIONS_UNDERLYINGS, format_options_digest

from tp_core.db.repos import FeatureRepo
from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import now_ist
from tp_scheduler.context import JobContext

log = get_logger(__name__)


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    holidays = await ctx.events.holidays()
    today = for_date or now_ist().date()
    if today.weekday() >= 5 or today in holidays:
        return

    features = FeatureRepo(ctx.db)
    per_underlying: dict[str, tuple[dict[str, float], date | None]] = {}
    for name in OPTIONS_UNDERLYINGS:
        values, ts = await features.latest(name)
        per_underlying[name] = (values, ts.date() if ts else None)

    have = [n for n, (v, _) in per_underlying.items() if v]
    message = format_options_digest(per_underlying)
    await ctx.alert(Severity.INFO, f"signal_options_{today.isoformat()}", message)
    log.info("options_digest_sent", date=today.isoformat(), with_data=have)
