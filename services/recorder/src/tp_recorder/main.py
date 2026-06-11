"""Recorder service entrypoint.

Tasks:
  1. websocket feed consumer (hot set) -> validator -> batch writer -> ticks
  2. periodic batch flusher
  3. full-chain REST poller -> option_chain
  4. staleness watchdog -> P1 alert + gap record on silent feed
  5. health/metrics server
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

from tp_core.config import get_settings
from tp_core.db import Database
from tp_core.db.repos import (
    EventsRepo,
    InstrumentRepo,
    MarketDataRepo,
    OpsRepo,
    TokenRepo,
)
from tp_core.models import Severity, Tick
from tp_core.redis import AlertEvent, AlertQueue, RedisBus
from tp_core.telemetry import HealthState, configure_logging, get_logger, serve_health
from tp_core.timeutils import is_market_hours, now_utc
from tp_recorder.batch_writer import TickBatchWriter
from tp_recorder.chain_poller import ChainPoller
from tp_recorder.subscriptions import SubscriptionSet, build_subscription_set
from tp_recorder.validators import TickValidator
from tp_upstox.auth import UpstoxAuth
from tp_upstox.feed import FeedQuote, MarketFeed, run_feed_with_reconnect
from tp_upstox.rest import INDEX_KEYS, UpstoxRest

log = get_logger(__name__)

STALENESS_LIMIT = timedelta(seconds=30)


class RecorderService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.db = Database(self.settings)
        self.bus = RedisBus(self.settings)
        self.alerts = AlertQueue(self.bus)
        self.instruments = InstrumentRepo(self.db)
        self.market_data = MarketDataRepo(self.db)
        self.ops = OpsRepo(self.db)
        self.auth = UpstoxAuth(self.settings, TokenRepo(self.db))
        self.rest = UpstoxRest(self.settings, self.auth)
        self.health = HealthState(service="recorder")
        self.validator = TickValidator()
        self.subs: SubscriptionSet | None = None
        self.writer: TickBatchWriter | None = None
        self._last_feed_at = now_utc()

    async def _alert(self, severity: Severity, dedup_key: str, message: str) -> None:
        await self.alerts.push(
            AlertEvent(severity=severity, source="recorder", dedup_key=dedup_key, message=message)
        )

    async def _spot_estimates(self) -> dict[str, Decimal]:
        keys = [INDEX_KEYS["NIFTY"], INDEX_KEYS["SENSEX"]]
        try:
            quotes = await self.rest.ltp(keys)
        except Exception:
            log.exception("spot_estimate_failed")
            return {}
        by_name = {}
        for name, key in (("NIFTY", INDEX_KEYS["NIFTY"]), ("SENSEX", INDEX_KEYS["SENSEX"])):
            if key in quotes:
                by_name[name] = Decimal(str(quotes[key]))
        return by_name

    async def _handle_quotes(self, quotes: list[FeedQuote]) -> None:
        assert self.subs is not None and self.writer is not None
        self._last_feed_at = now_utc()
        ts = now_utc()
        ticks = []
        for q in quotes:
            instrument_id = self.subs.key_to_id.get(q.upstox_key)
            if instrument_id is None:
                continue
            tick = Tick(
                ts=ts,
                instrument_id=instrument_id,
                ltp=q.ltp,
                bid=q.bid,
                ask=q.ask,
                bid_qty=q.bid_qty,
                ask_qty=q.ask_qty,
                volume=q.volume,
                oi=q.oi,
            )
            if self.validator.validate(tick):
                ticks.append(tick)
        await self.writer.add(ticks)

    async def _on_reconnect(self) -> None:
        """Bridge a feed gap: record it and refresh the chain immediately."""
        gap_start = self._last_feed_at
        await self.ops.record_gap("ws_feed", gap_start, now_utc())
        await self._alert(
            Severity.P2, "ws_reconnect", f"Feed reconnected; gap since {gap_start.isoformat()}"
        )

    async def _staleness_watchdog(self, holidays: frozenset[date]) -> None:
        while True:
            await asyncio.sleep(10)
            now = now_utc()
            if not is_market_hours(now, holidays):
                self.health.set_ready("feed", True)  # off-hours: silence is fine
                continue
            stale = now - self._last_feed_at > STALENESS_LIMIT
            self.health.set_ready("feed", not stale)
            if stale:
                await self._alert(
                    Severity.P1,
                    "feed_stale",
                    f"No feed messages for {(now - self._last_feed_at).seconds}s "
                    "during market hours",
                )

    async def run(self) -> None:
        token = await self.auth.current_token()
        if token is None:
            await self._alert(
                Severity.P1, "no_token", "Recorder started without a valid Upstox token"
            )
            log.error("no_valid_token_waiting")
            while token is None:
                await asyncio.sleep(30)
                token = await self.auth.current_token()

        holidays = await EventsRepo(self.db).holidays()
        spots = await self._spot_estimates()
        self.subs = await build_subscription_set(
            self.instruments,
            spots,
            now_utc().date(),
            self.settings.recorder_atm_strike_window,
            self.settings.upstox_ws_max_instruments,
        )
        self.writer = TickBatchWriter(
            self.market_data,
            self.subs.id_to_underlying,
            max_rows=self.settings.recorder_batch_max_rows,
            flush_seconds=self.settings.recorder_batch_flush_seconds,
        )
        poller = ChainPoller(
            self.rest,
            self.instruments,
            self.market_data,
            self.bus,
            self.settings.recorder_chain_poll_seconds,
            holidays,
        )

        self.health.set_ready("db", await self.db.ping())
        self.health.set_ready("redis", await self.bus.ping())
        self.health.set_ready("feed", True)

        def feed_factory() -> MarketFeed:
            assert self.subs is not None
            return MarketFeed(token, self.subs.keys)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                run_feed_with_reconnect(feed_factory, self._handle_quotes, self._on_reconnect),
                name="feed",
            )
            tg.create_task(self.writer.run_flusher(), name="flusher")
            tg.create_task(poller.run(), name="chain-poller")
            tg.create_task(self._staleness_watchdog(holidays), name="watchdog")


async def main() -> None:
    settings = get_settings()
    configure_logging("recorder", settings.log_level)
    service = RecorderService()
    health_task = asyncio.create_task(
        serve_health(service.health, settings.recorder_health_port), name="health"
    )
    try:
        await service.run()
    finally:
        health_task.cancel()
        await service.rest.close()
        await service.bus.close()
        await service.db.close()


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
