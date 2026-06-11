"""Redis access: pub/sub bus for real-time fan-out, streams for durable queues."""

from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis
from pydantic import BaseModel

from tp_core.config import Settings
from tp_core.redis.channels import ALERTS_CONSUMER_GROUP, Channel
from tp_core.redis.events import AlertEvent


class RedisBus:
    def __init__(self, settings: Settings) -> None:
        self._redis: aioredis.Redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    @property
    def raw(self) -> aioredis.Redis:
        return self._redis

    async def publish(self, channel: Channel, event: BaseModel) -> None:
        await self._redis.publish(channel.value, event.model_dump_json())

    async def subscribe(self, channel: Channel) -> AsyncIterator[str]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel.value)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield message["data"]
        finally:
            await pubsub.unsubscribe(channel.value)
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self._redis.aclose()


class AlertQueue:
    """Durable alert queue on a Redis stream. Producers XADD; the Telegram
    service consumes with a consumer group so alerts survive its restarts."""

    def __init__(self, bus: RedisBus) -> None:
        self._redis = bus.raw

    async def push(self, alert: AlertEvent) -> None:
        await self._redis.xadd(
            Channel.ALERTS_STREAM.value, {"payload": alert.model_dump_json()}, maxlen=10_000
        )

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                Channel.ALERTS_STREAM.value, ALERTS_CONSUMER_GROUP, id="0", mkstream=True
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume(self, consumer: str, block_ms: int = 5000) -> list[tuple[str, AlertEvent]]:
        """Read pending alerts; returns (stream_id, event) pairs to ack after send."""
        entries: Any = await self._redis.xreadgroup(
            ALERTS_CONSUMER_GROUP,
            consumer,
            {Channel.ALERTS_STREAM.value: ">"},
            count=50,
            block=block_ms,
        )
        out: list[tuple[str, AlertEvent]] = []
        for _stream, messages in entries or []:
            for stream_id, fields in messages:
                out.append((stream_id, AlertEvent.model_validate_json(fields["payload"])))
        return out

    async def ack(self, stream_ids: list[str]) -> None:
        if stream_ids:
            await self._redis.xack(Channel.ALERTS_STREAM.value, ALERTS_CONSUMER_GROUP, *stream_ids)
