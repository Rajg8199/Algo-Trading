"""Alert delivery: consumes the durable Redis stream, applies severity routing
and dedup, sends to the allowlisted chat.

P1   -> immediately
P2   -> batched every 5 minutes
INFO -> batched into a daily digest at 18:00 IST (heartbeats pass through,
        they exist to be seen at specific times)
"""

import asyncio
from datetime import timedelta

from aiogram import Bot

from tp_core.models import Severity
from tp_core.redis import AlertEvent, AlertQueue
from tp_core.telemetry.logging import get_logger
from tp_core.telemetry.metrics import ALERTS_SENT
from tp_core.timeutils import now_ist, now_utc

log = get_logger(__name__)

DEDUP_WINDOW = timedelta(minutes=15)
P2_BATCH_SECONDS = 300
PASSTHROUGH_DEDUP_PREFIXES = ("heartbeat_", "token_refreshed")


class AlertRouter:
    def __init__(self, bot: Bot, chat_id: int, queue: AlertQueue) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._queue = queue
        self._last_sent: dict[str, object] = {}
        self._p2_buffer: list[AlertEvent] = []
        self._info_buffer: list[AlertEvent] = []

    async def run(self) -> None:
        await self._queue.ensure_group()
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._consume(), name="alert-consume")
            tg.create_task(self._flush_p2_loop(), name="alert-p2-flush")
            tg.create_task(self._flush_info_loop(), name="alert-info-digest")

    async def _consume(self) -> None:
        while True:
            entries = await self._queue.consume(consumer="telegram-1")
            ack_ids: list[str] = []
            for stream_id, alert in entries:
                try:
                    await self._route(alert)
                    ack_ids.append(stream_id)
                except Exception:
                    log.exception("alert_route_failed", dedup_key=alert.dedup_key)
            await self._queue.ack(ack_ids)

    async def _route(self, alert: AlertEvent) -> None:
        if self._is_duplicate(alert):
            return
        if alert.severity is Severity.P1:
            await self._send(f"🚨 P1 · {alert.source}\n{alert.message}")
            ALERTS_SENT.labels(severity="P1").inc()
        elif alert.severity is Severity.P2:
            self._p2_buffer.append(alert)
        elif alert.dedup_key.startswith(PASSTHROUGH_DEDUP_PREFIXES):
            await self._send(alert.message)
            ALERTS_SENT.labels(severity="INFO").inc()
        else:
            self._info_buffer.append(alert)

    def _is_duplicate(self, alert: AlertEvent) -> bool:
        last = self._last_sent.get(alert.dedup_key)
        now = now_utc()
        if last is not None and now - last < DEDUP_WINDOW:  # type: ignore[operator]
            return True
        self._last_sent[alert.dedup_key] = now
        return False

    async def _flush_p2_loop(self) -> None:
        while True:
            await asyncio.sleep(P2_BATCH_SECONDS)
            if not self._p2_buffer:
                continue
            batch, self._p2_buffer = self._p2_buffer, []
            lines = "\n".join(f"• [{a.source}] {a.message}" for a in batch[:20])
            await self._send(f"⚠️ P2 ({len(batch)})\n{lines}")
            ALERTS_SENT.labels(severity="P2").inc(len(batch))

    async def _flush_info_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            local = now_ist()
            if local.hour == 18 and local.minute == 0 and self._info_buffer:
                batch, self._info_buffer = self._info_buffer, []
                lines = "\n".join(f"• [{a.source}] {a.message}" for a in batch[:50])
                await self._send(f"📋 Daily digest ({len(batch)})\n{lines}")
                ALERTS_SENT.labels(severity="INFO").inc(len(batch))

    async def _send(self, text: str) -> None:
        await self._bot.send_message(self._chat_id, text[:4000], disable_web_page_preview=True)
