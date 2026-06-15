"""EOD scalp forward-test review.

Grades the day's emitted scalp signals against what the index actually did
(target hit first = WIN, stop first = LOSS, neither = OPEN), persists the
outcome + realized R, and Telegrams an honest scorecard. This is how an
UNVALIDATED cue earns (or loses) trust — measured, not asserted.
"""

from datetime import date, datetime

from sqlalchemy import select, text, update
from tp_research.scalp import evaluate_outcome, summarize_review

from tp_core.db.orm import ScalpSignalRow
from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import now_ist
from tp_scheduler.context import JobContext

log = get_logger(__name__)

_LTPS_SQL = text("""
    SELECT t.ts, t.ltp
    FROM ticks t JOIN instruments i USING (instrument_id)
    WHERE i.underlying = :u AND i.segment = 'INDEX'
      AND i.upstox_key NOT LIKE 'NSEBHAV%' AND t.ts::date = :day
    ORDER BY t.ts
""")


def _f(v: float | None, d: int = 2) -> str:
    return "—" if v is None else f"{v:.{d}f}"


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    holidays = await ctx.events.holidays()
    today = for_date or now_ist().date()
    if today.weekday() >= 5 or today in holidays:
        return

    async with ctx.db.session() as s:
        pending = list(
            (
                await s.execute(
                    select(ScalpSignalRow).where(
                        ScalpSignalRow.outcome.is_(None),
                        text("scalp_signals.ts::date = :d").bindparams(d=today),
                    )
                )
            ).scalars()
        )

    # load today's live index price series once per underlying
    series: dict[str, list[tuple[datetime, float]]] = {}
    for u in {r.underlying for r in pending}:
        async with ctx.db.session() as s:
            rows = (await s.execute(_LTPS_SQL, {"u": u, "day": today})).all()
        series[u] = [(t, float(p)) for t, p in rows]

    graded: list[tuple[str, float]] = []
    now = now_ist()
    for r in pending:
        future = [p for t, p in series.get(r.underlying, []) if t > r.ts]
        outcome, exit_price, r_mult = evaluate_outcome(
            r.side, float(r.entry), float(r.stop), float(r.target), future
        )
        graded.append((outcome, r_mult))
        async with ctx.db.session() as s:
            await s.execute(
                update(ScalpSignalRow)
                .where(ScalpSignalRow.id == r.id)
                .values(outcome=outcome, exit_price=exit_price, r_multiple=r_mult, evaluated_at=now)
            )

    today_stats = summarize_review(graded)

    # trailing 7-day picture from all graded rows
    async with ctx.db.session() as s:
        recent = (
            await s.execute(
                text("""
                    SELECT outcome, r_multiple FROM scalp_signals
                    WHERE outcome IS NOT NULL AND ts > now() - interval '7 days'
                """)
            )
        ).all()
    recent_stats = summarize_review([(o, float(rm)) for o, rm in recent if rm is not None])

    msg = _format(today, today_stats, recent_stats)
    await ctx.alert(Severity.INFO, f"signal_scalp_review_{today.isoformat()}", msg)
    log.info("scalp_review", date=today.isoformat(), graded=len(graded))


def _format(day: date, today: object, recent: object) -> str:
    t = today  # ReviewStats
    r = recent
    body = (
        f"📋 Scalp forward-test · {day:%d %b}\n"
        f"Today: {t.n} signals — {t.wins}W / {t.losses}L / {t.open}open"  # type: ignore[attr-defined]
        f" · hit {_pct(t.hit_rate)} · exp {_f(t.expectancy_r)}R\n"  # type: ignore[attr-defined]
        f"7d: {r.n} signals · hit {_pct(r.hit_rate)} · exp {_f(r.expectancy_r)}R"  # type: ignore[attr-defined]
    )
    verdict = ""
    if r.expectancy_r is not None and r.expectancy_r <= 0:  # type: ignore[attr-defined]
        verdict = "\n\n⚠️ Negative expectancy so far — do NOT trade these live."
    return body + verdict


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"
