"""Market data feed: wraps the official Upstox streamer (which owns the
protobuf wire format) behind an asyncio interface we control.

Design:
- The SDK streamer runs in its own thread (it is callback/thread based).
- Callbacks push decoded messages into an asyncio.Queue via
  loop.call_soon_threadsafe; the recorder consumes the queue.
- Reconnect policy is OURS (exponential backoff + jitter), not the SDK's:
  on any disconnect we tear the streamer down and rebuild it, and we surface
  the event so the recorder can bridge the gap with a REST snapshot.
"""

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from tp_core.telemetry.logging import get_logger
from tp_core.telemetry.metrics import WS_CONNECTED, WS_RECONNECTS
from tp_core.timeutils import now_utc

log = get_logger(__name__)


@dataclass(frozen=True)
class FeedQuote:
    """Normalized quote extracted from a feed message."""

    upstox_key: str
    ltp: Decimal
    bid: Decimal | None
    ask: Decimal | None
    bid_qty: int | None
    ask_qty: int | None
    volume: int | None
    oi: int | None


class FeedDisconnectedError(Exception):
    pass


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_feed_message(message: dict[str, Any]) -> list[FeedQuote]:
    """Parse one decoded streamer message ('full' mode) into quotes.

    Tolerant by design: fields the SDK omits become None; messages without
    an LTP are dropped. The structure asserted here is covered by unit tests
    against captured fixtures, and by a live smoke test (marker: live_creds).
    """
    quotes: list[FeedQuote] = []
    for key, feed in (message.get("feeds") or {}).items():
        full = (feed.get("fullFeed") or {}).get("marketFF") or (feed.get("fullFeed") or {}).get(
            "indexFF"
        )
        if full is None:
            ltpc = feed.get("ltpc") or {}
            ltp = _decimal(ltpc.get("ltp"))
            if ltp is not None:
                quotes.append(FeedQuote(key, ltp, None, None, None, None, None, None))
            continue
        ltpc = full.get("ltpc") or {}
        ltp = _decimal(ltpc.get("ltp"))
        if ltp is None:
            continue
        bid = ask = None
        bid_qty = ask_qty = None
        depth = ((full.get("marketLevel") or {}).get("bidAskQuote")) or []
        if depth:
            top = depth[0]
            bid = _decimal(top.get("bidP"))
            ask = _decimal(top.get("askP"))
            bid_qty = top.get("bidQ")
            ask_qty = top.get("askQ")
        quotes.append(
            FeedQuote(
                upstox_key=key,
                ltp=ltp,
                bid=bid,
                ask=ask,
                bid_qty=int(bid_qty) if bid_qty is not None else None,
                ask_qty=int(ask_qty) if ask_qty is not None else None,
                volume=full.get("vtt"),
                oi=int(full["oi"]) if full.get("oi") is not None else None,
            )
        )
    return quotes


class MarketFeed:
    """Owns the SDK streamer lifecycle and exposes an async message queue."""

    def __init__(self, access_token: str, instrument_keys: list[str]) -> None:
        self._access_token = access_token
        self._instrument_keys = instrument_keys
        self._queue: asyncio.Queue[list[FeedQuote] | FeedDisconnectedError] = asyncio.Queue(
            maxsize=10_000
        )
        self._loop = asyncio.get_event_loop()
        self._streamer: Any = None
        self._last_message_at = now_utc()

    @property
    def last_message_at(self) -> Any:
        return self._last_message_at

    def _on_message(self, message: dict[str, Any]) -> None:
        """SDK thread context — hand off to the event loop, never block."""
        self._last_message_at = now_utc()
        quotes = parse_feed_message(message)
        if not quotes:
            return
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, quotes)
        except (asyncio.QueueFull, RuntimeError):
            log.warning("feed_queue_full_dropping", count=len(quotes))

    def _on_error(self, error: Any) -> None:
        log.error("feed_error", error=str(error))
        self._loop.call_soon_threadsafe(self._queue.put_nowait, FeedDisconnectedError(str(error)))

    def _on_close(self, *args: Any) -> None:
        WS_CONNECTED.set(0)
        self._loop.call_soon_threadsafe(self._queue.put_nowait, FeedDisconnectedError("closed"))

    def connect(self) -> None:
        import upstox_client

        configuration = upstox_client.Configuration()
        configuration.access_token = self._access_token
        streamer = upstox_client.MarketDataStreamerV3(
            upstox_client.ApiClient(configuration),
            instrumentKeys=self._instrument_keys,
            mode="full",
        )
        streamer.on("message", self._on_message)
        streamer.on("error", self._on_error)
        streamer.on("close", self._on_close)
        streamer.auto_reconnect(False)  # reconnect policy is ours
        streamer.connect()
        self._streamer = streamer
        WS_CONNECTED.set(1)
        log.info("feed_connected", instruments=len(self._instrument_keys))

    def disconnect(self) -> None:
        if self._streamer is not None:
            try:
                self._streamer.disconnect()
            except Exception as exc:
                log.warning("feed_disconnect_error", error=str(exc))
            self._streamer = None
        WS_CONNECTED.set(0)

    async def messages(self) -> list[FeedQuote]:
        """Next quote batch; raises FeedDisconnectedError when the feed drops."""
        item = await self._queue.get()
        if isinstance(item, FeedDisconnectedError):
            raise item
        return item


async def run_feed_with_reconnect(
    feed_factory: Callable[[], MarketFeed],
    handler: Callable[[list[FeedQuote]], Any],
    on_reconnect: Callable[[], Any],
    max_backoff: float = 60.0,
) -> None:
    """Supervision loop: run a feed, on failure rebuild with backoff + jitter,
    invoking on_reconnect so the caller can bridge the data gap via REST."""
    backoff = 1.0
    while True:
        feed = feed_factory()
        try:
            feed.connect()
            backoff = 1.0
            while True:
                quotes = await feed.messages()
                await handler(quotes)
        except FeedDisconnectedError as exc:
            log.warning("feed_disconnected", reason=str(exc), retry_in=backoff)
        except asyncio.CancelledError:
            feed.disconnect()
            raise
        except Exception as exc:
            log.error("feed_unexpected_error", error=str(exc), retry_in=backoff)
        feed.disconnect()
        WS_RECONNECTS.inc()
        await asyncio.sleep(backoff + random.uniform(0, backoff / 2))  # noqa: S311
        backoff = min(backoff * 2, max_backoff)
        await on_reconnect()
