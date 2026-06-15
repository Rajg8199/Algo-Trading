"""Scheduler service: APScheduler cron jobs, all times IST.

Every job is wrapped with metrics + error alerting; a job that throws is
reported, never silently swallowed. EOD downloads retry hourly via their
own retry triggers until the source publishes.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from tp_core.config import get_settings
from tp_core.models import Severity
from tp_core.telemetry import HealthState, configure_logging, get_logger, serve_health
from tp_core.telemetry.metrics import JOB_DURATION, JOB_RUNS
from tp_core.timeutils import IST
from tp_scheduler.context import JobContext, build_context
from tp_scheduler.jobs import (
    breakout_scan,
    data_validation,
    heartbeat,
    instruments_refresh,
    nse_eod,
    options_digest,
    token_check,
)
from tp_scheduler.jobs import feature_engine as feature_engine_job
from tp_scheduler.jobs import paper_review as paper_review_job
from tp_scheduler.jobs import vol_metrics as vol_metrics_job

log = get_logger(__name__)

JobFn = Callable[[JobContext], Awaitable[None]]


def wrap(name: str, fn: JobFn, ctx: JobContext) -> Callable[[], Awaitable[None]]:
    async def runner() -> None:
        start = time.monotonic()
        try:
            await fn(ctx)
            JOB_RUNS.labels(job=name, outcome="success").inc()
        except FileNotFoundError:
            # EOD file not yet published — expected; hourly retry trigger covers it.
            JOB_RUNS.labels(job=name, outcome="not_ready").inc()
        except Exception as exc:
            JOB_RUNS.labels(job=name, outcome="error").inc()
            log.exception("job_failed", job=name)
            await ctx.alert(Severity.P2, f"job_failed_{name}", f"Job {name} failed: {exc}")
        finally:
            JOB_DURATION.labels(job=name).observe(time.monotonic() - start)

    return runner


def weekday_cron(hour: int | str, minute: int) -> CronTrigger:
    return CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=IST)


def register_jobs(scheduler: AsyncIOScheduler, ctx: JobContext) -> None:
    jobs: list[tuple[str, JobFn, CronTrigger]] = [
        ("token_check", token_check.run, weekday_cron(8, 30)),
        ("token_check_late", token_check.run, weekday_cron(9, 0)),
        ("instruments_refresh", instruments_refresh.run, weekday_cron(8, 35)),
        ("vol_metrics", vol_metrics_job.run, weekday_cron(16, 0)),
        ("feature_engine", feature_engine_job.run, weekday_cron(16, 15)),
        ("options_digest", options_digest.run, weekday_cron(16, 20)),
        ("paper_review", paper_review_job.run, weekday_cron(16, 30)),
        ("nse_eod", nse_eod.run, weekday_cron("18-22", 30)),
        ("breakout_scan", breakout_scan.run, weekday_cron("18-22", 45)),
        ("data_validation", data_validation.run, weekday_cron(21, 0)),
        ("heartbeat_open", heartbeat.run, weekday_cron(9, 20)),
        ("heartbeat_midday", heartbeat.run, weekday_cron(12, 30)),
        ("heartbeat_close", heartbeat.run, weekday_cron(15, 35)),
    ]
    for name, fn, trigger in jobs:
        scheduler.add_job(wrap(name, fn, ctx), trigger, id=name, max_instances=1, coalesce=True)
    log.info("jobs_registered", count=len(jobs))


async def main() -> None:
    settings = get_settings()
    configure_logging("scheduler", settings.log_level)
    ctx = build_context()
    health = HealthState(service="scheduler")

    scheduler = AsyncIOScheduler(timezone=IST)
    register_jobs(scheduler, ctx)
    scheduler.start()
    health.set_ready("scheduler", True)
    health.set_ready("db", await ctx.db.ping())
    health.set_ready("redis", await ctx.bus.ping())

    try:
        await serve_health(health, settings.scheduler_health_port)
    finally:
        scheduler.shutdown(wait=False)
        await ctx.bus.close()
        await ctx.db.close()


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
