"""Validation runner: execute every check, persist results to dq_checks,
return failures for alerting. The scheduler job owns scheduling and alerts."""

from dataclasses import dataclass
from datetime import date

from tp_core.db import Database
from tp_core.db.repos import OpsRepo
from tp_core.telemetry.logging import get_logger
from tp_research.validation.checks import ALL_CHECKS, CheckResult

log = get_logger(__name__)


@dataclass(frozen=True)
class ValidationReport:
    trade_date: date
    results: list[CheckResult]

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    def summary_line(self) -> str:
        return f"DQ {self.trade_date}: {self.passed_count}/{len(self.results)} passed" + (
            "  FAILED: " + ", ".join(f.name for f in self.failures) if self.failures else " ✓"
        )


async def run_validation(db: Database, trade_date: date) -> ValidationReport:
    ops = OpsRepo(db)
    results: list[CheckResult] = []
    for check in ALL_CHECKS:
        try:
            results.extend(await check(db, trade_date))
        except Exception:
            # A check that cannot run is itself a failed check, loudly.
            name = getattr(check, "__name__", str(check))
            log.exception("validation_check_errored", check=name)
            from tp_core.models import Severity

            results.append(
                CheckResult(f"{name}_errored", False, Severity.P1, {"error": "check raised"})
            )
    for r in results:
        await ops.record_dq_check(trade_date, r.name, r.passed, r.details)
    report = ValidationReport(trade_date, results)
    log.info("validation_done", summary=report.summary_line())
    return report
