"""Full-chain REST poller: every N seconds during market hours, snapshot the
complete option chain (all strikes, front expiries) for each underlying."""

import asyncio
import time
from datetime import date

from tp_core.db.repos import InstrumentRepo, MarketDataRepo
from tp_core.redis import ChainSnapshotEvent, Channel, RedisBus
from tp_core.telemetry.logging import get_logger
from tp_core.telemetry.metrics import (
    CHAIN_ROWS_INGESTED,
    CHAIN_SNAPSHOT_AGE,
    DB_WRITE_LATENCY,
)
from tp_core.timeutils import is_market_hours, now_utc
from tp_recorder.validators import validate_chain_row
from tp_upstox.rest import UpstoxRest

log = get_logger(__name__)


class ChainPoller:
    def __init__(
        self,
        rest: UpstoxRest,
        instruments: InstrumentRepo,
        market_data: MarketDataRepo,
        bus: RedisBus,
        poll_seconds: int,
        holidays: frozenset[date],
    ) -> None:
        self._rest = rest
        self._instruments = instruments
        self._market_data = market_data
        self._bus = bus
        self._poll_seconds = poll_seconds
        self._holidays = holidays
        self._key_to_id_cache: dict[str, dict[str, int]] = {}

    async def run(self) -> None:
        while True:
            started = time.monotonic()
            if is_market_hours(now_utc(), self._holidays):
                for underlying in ("NIFTY", "SENSEX"):
                    try:
                        await self._poll_one(underlying)
                    except Exception:
                        log.exception("chain_poll_failed", underlying=underlying)
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(1.0, self._poll_seconds - elapsed))

    async def _poll_one(self, underlying: str) -> None:
        today = now_utc().date()
        expiries = (await self._instruments.expiries(underlying, after=today))[:3]
        for expiry in expiries:
            key_to_id = await self._key_map(underlying, expiry)
            rows = await self._rest.option_chain(underlying, expiry, key_to_id)
            valid = [r for r in rows if validate_chain_row(r)]
            start = time.monotonic()
            written = await self._market_data.insert_chain_rows(valid)
            DB_WRITE_LATENCY.labels(table="option_chain").observe(time.monotonic() - start)
            CHAIN_ROWS_INGESTED.labels(underlying=underlying).inc(written)
            CHAIN_SNAPSHOT_AGE.labels(underlying=underlying).set(0)
            await self._bus.publish(
                Channel.CHAIN_SNAPSHOTS,
                ChainSnapshotEvent(
                    ts=now_utc(),
                    underlying=underlying,
                    expiry=expiry.isoformat(),
                    row_count=written,
                ),
            )

    async def _key_map(self, underlying: str, expiry: date) -> dict[str, int]:
        cache_key = f"{underlying}:{expiry.isoformat()}"
        if cache_key not in self._key_to_id_cache:
            rows = await self._instruments.active_options(underlying, expiry)
            self._key_to_id_cache[cache_key] = {r.upstox_key: r.instrument_id for r in rows}
        return self._key_to_id_cache[cache_key]
