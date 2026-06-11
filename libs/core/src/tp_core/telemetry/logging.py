"""Structured JSON logging. One line per event, machine-parseable, shipped to Loki.

Usage:
    configure_logging(service="recorder", level="INFO")
    log = get_logger(__name__)
    log.info("tick_batch_flushed", rows=482, lag_ms=12)
"""

import logging
import sys
from typing import Any

import structlog


def configure_logging(service: str, level: str = "INFO") -> None:
    logging.basicConfig(stream=sys.stdout, level=level.upper(), format="%(message)s")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
