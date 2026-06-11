"""Channel registry. Every pub/sub channel and stream name is defined here —
no string literals scattered through services."""

from enum import StrEnum


class Channel(StrEnum):
    # Pub/sub (fire-and-forget fan-out; consumers that are down miss messages,
    # which is correct for real-time ticks — the DB is the system of record)
    TICKS = "md.ticks"
    CHAIN_SNAPSHOTS = "md.chain"
    SYSTEM = "sys.events"

    # Streams (durable queues; consumers ack)
    ALERTS_STREAM = "alerts.stream"


ALERTS_CONSUMER_GROUP = "telegram"
