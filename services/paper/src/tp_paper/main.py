"""Paper trading lab entrypoint.

Event-driven off the recorder: every ChainSnapshotEvent on the Redis bus
triggers one engine pass over the freshest recorded snapshot. No recorder
running => the lab idles. No broker modules exist in this service.

Params: datalake/paper/params.json overrides VRPParams defaults; changing it
is the ONLY way to change strategy behavior (the learning layer recommends,
a human edits the file — nothing self-deploys).
"""

import asyncio
import json
from dataclasses import fields
from pathlib import Path

from tp_backtest.strategies.vrp import VRPParams

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.models import Severity
from tp_core.redis import AlertEvent, AlertQueue, ChainSnapshotEvent, Channel, RedisBus
from tp_core.telemetry import HealthState, configure_logging, get_logger, serve_health
from tp_core.timeutils import is_market_hours, now_utc
from tp_paper.engine import PaperEngine

log = get_logger(__name__)


def load_params(root: Path) -> VRPParams:
    path = root / "paper" / "params.json"
    if not path.is_file():
        return VRPParams()
    raw = json.loads(path.read_text())
    valid = {f.name for f in fields(VRPParams)} - {"excluded_entry_days"}
    return VRPParams(**{k: v for k, v in raw.items() if k in valid})


async def main() -> None:
    settings = get_settings()
    configure_logging("paper", settings.log_level)
    db = Database(settings)
    bus = RedisBus(settings)
    alerts = AlertQueue(bus)
    params = load_params(Path(settings.datalake_root))
    engine = PaperEngine(db, params)
    await engine.start()

    health = HealthState(service="paper")
    health.set_ready("db", await db.ping())
    health.set_ready("redis", await bus.ping())
    health.set_ready("engine", True)

    async def push(severity: Severity, key: str, message: str) -> None:
        await alerts.push(
            AlertEvent(severity=severity, source="paper", dedup_key=key, message=message)
        )

    await push(
        Severity.INFO,
        "paper_started",
        f"🧪 Paper lab online — {engine.strategy.name}, forward-test mode (UNVALIDATED)",
    )

    async def consume() -> None:
        async for raw in bus.subscribe(Channel.CHAIN_SNAPSHOTS):
            try:
                event = ChainSnapshotEvent.model_validate_json(raw)
            except ValueError:
                continue
            if not is_market_hours(now_utc()):
                continue
            try:
                for severity, key, message in await engine.on_snapshot(event.underlying):
                    await push(severity, key, message)
            except Exception:
                log.exception("paper_snapshot_failed", underlying=event.underlying)
                await push(Severity.P2, "paper_engine_error", "Paper engine error; see logs")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(consume(), name="paper-consume")
        tg.create_task(serve_health(health, 8004), name="health")


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
