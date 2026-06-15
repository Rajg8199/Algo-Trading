"""Feature engine: evaluate the registry for each underlying and persist.

A feature evaluating to None is SKIPPED (insufficient history / missing data),
logged with a count — never written as 0 or interpolated. The engine returns
a summary the scheduler job uses for reporting and alerting.
"""

from dataclasses import dataclass
from datetime import date, time

from tp_core.db import Database
from tp_core.db.repos import FeatureRepo
from tp_core.telemetry.logging import get_logger
from tp_research.chain import CLOSE_SNAPSHOT_IST
from tp_research.features.context import build_context
from tp_research.features.registry import REGISTRY

log = get_logger(__name__)

UNDERLYINGS = ("NIFTY", "SENSEX")


@dataclass(frozen=True)
class EngineSummary:
    trade_date: date
    computed: int
    skipped: int
    failed: int

    @property
    def coverage_pct(self) -> float:
        total = self.computed + self.skipped + self.failed
        return 100.0 * self.computed / total if total else 0.0


async def run_feature_engine(
    db: Database, trade_date: date, close_cut: time = CLOSE_SNAPSHOT_IST
) -> EngineSummary:
    features = FeatureRepo(db)
    computed = skipped = failed = 0
    rows: list[dict[str, object]] = []

    for underlying in UNDERLYINGS:
        ctx = await build_context(db, underlying, trade_date, close_cut=close_cut)
        for spec in REGISTRY:
            try:
                value = spec.fn(ctx)
            except Exception:
                failed += 1
                log.exception("feature_failed", feature=spec.name, underlying=underlying)
                continue
            if value is None:
                skipped += 1
                continue
            computed += 1
            rows.append(
                {
                    "feature_name": spec.name,
                    "feature_version": spec.version,
                    "entity": underlying,
                    "ts": ctx.ts,
                    "value": value,
                    "extra": {"group": spec.group},
                }
            )

    await features.upsert_many(rows)
    summary = EngineSummary(trade_date, computed, skipped, failed)
    log.info(
        "feature_engine_done",
        date=trade_date.isoformat(),
        computed=computed,
        skipped=skipped,
        failed=failed,
        coverage_pct=round(summary.coverage_pct, 1),
    )
    return summary
