"""Batched tick persistence: accumulate, flush on size or age, never block
the feed consumer on the database."""

import asyncio
import time

from tp_core.db.repos import MarketDataRepo
from tp_core.models import Tick
from tp_core.telemetry.logging import get_logger
from tp_core.telemetry.metrics import DB_WRITE_LATENCY, TICKS_INGESTED

log = get_logger(__name__)


class TickBatchWriter:
    def __init__(
        self,
        repo: MarketDataRepo,
        underlying_of: dict[int, str],
        max_rows: int = 500,
        flush_seconds: float = 1.0,
    ) -> None:
        self._repo = repo
        self._underlying_of = underlying_of
        self._max_rows = max_rows
        self._flush_seconds = flush_seconds
        self._buffer: list[Tick] = []
        self._lock = asyncio.Lock()

    async def add(self, ticks: list[Tick]) -> None:
        async with self._lock:
            self._buffer.extend(ticks)
            if len(self._buffer) >= self._max_rows:
                await self._flush_locked()

    async def run_flusher(self) -> None:
        """Periodic flush so quiet periods still persist promptly."""
        while True:
            await asyncio.sleep(self._flush_seconds)
            async with self._lock:
                await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        start = time.monotonic()
        try:
            await self._repo.insert_ticks(batch)
        except Exception:
            # Put the batch back; better duplicate-safe retries than data loss.
            self._buffer = batch + self._buffer
            log.exception("tick_flush_failed", rows=len(batch))
            return
        DB_WRITE_LATENCY.labels(table="ticks").observe(time.monotonic() - start)
        for tick in batch:
            TICKS_INGESTED.labels(
                underlying=self._underlying_of.get(tick.instrument_id, "UNKNOWN")
            ).inc()
