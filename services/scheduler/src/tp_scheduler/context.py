"""Shared dependencies for jobs, built once at service start."""

from dataclasses import dataclass

from tp_core.config import Settings, get_settings
from tp_core.db import Database
from tp_core.db.repos import (
    EventsRepo,
    InstrumentRepo,
    MarketDataRepo,
    OpsRepo,
    TokenRepo,
    VolMetricsRepo,
)
from tp_core.models import Severity
from tp_core.redis import AlertEvent, AlertQueue, RedisBus
from tp_upstox.auth import UpstoxAuth


@dataclass
class JobContext:
    settings: Settings
    db: Database
    bus: RedisBus
    alerts: AlertQueue
    instruments: InstrumentRepo
    market_data: MarketDataRepo
    ops: OpsRepo
    vol_metrics: VolMetricsRepo
    events: EventsRepo
    auth: UpstoxAuth

    async def alert(self, severity: Severity, dedup_key: str, message: str) -> None:
        await self.alerts.push(
            AlertEvent(severity=severity, source="scheduler", dedup_key=dedup_key, message=message)
        )


def build_context() -> JobContext:
    settings = get_settings()
    db = Database(settings)
    bus = RedisBus(settings)
    return JobContext(
        settings=settings,
        db=db,
        bus=bus,
        alerts=AlertQueue(bus),
        instruments=InstrumentRepo(db),
        market_data=MarketDataRepo(db),
        ops=OpsRepo(db),
        vol_metrics=VolMetricsRepo(db),
        events=EventsRepo(db),
        auth=UpstoxAuth(settings, TokenRepo(db)),
    )
