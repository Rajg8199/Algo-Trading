"""Walk-forward window machinery (3D).

Leakage controls:
- purge gap between train end and validation start (positions span days)
- expiry-aware snapping: validation windows start the day AFTER a weekly
  expiry, so no position straddles a split boundary
- test window: the FINAL holdout, untouched until every other gate passes;
  the framework refuses to run it more than once per experiment.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

EXPIRY_WEEKDAY = {"NIFTY": 1, "SENSEX": 3}  # Tue / Thu (2026 regime)


@dataclass(frozen=True)
class Window:
    train_start: date
    train_end: date
    validate_start: date
    validate_end: date


def next_expiry_on_or_after(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def snap_past_expiry(d: date, weekday: int) -> date:
    """First day strictly after the next expiry on/after d."""
    return next_expiry_on_or_after(d, weekday) + timedelta(days=1)


def walk_forward_windows(
    start: date,
    end: date,
    train_days: int,
    validate_days: int,
    purge_days: int = 7,
    anchored: bool = False,
    underlying: str = "NIFTY",
) -> Iterator[Window]:
    weekday = EXPIRY_WEEKDAY[underlying]
    train_start = start
    cursor = start
    prev_validate_end: date | None = None
    while True:
        train_end = cursor + timedelta(days=train_days - 1)
        # Expiry-snapped start, respecting BOTH the purge gap and the previous
        # validation window's end (snapping can otherwise create overlap).
        candidate = train_end + timedelta(days=purge_days)
        if prev_validate_end is not None and candidate <= prev_validate_end:
            candidate = prev_validate_end + timedelta(days=1)
        validate_start = snap_past_expiry(candidate, weekday)
        validate_end = validate_start + timedelta(days=validate_days - 1)
        if validate_end > end:
            return
        yield Window(
            train_start=train_start if anchored else cursor,
            train_end=train_end,
            validate_start=validate_start,
            validate_end=validate_end,
        )
        prev_validate_end = validate_end
        cursor = cursor + timedelta(days=validate_days)


def assert_no_overlap(windows: list[Window]) -> None:
    """Sanity invariant: every validation range is disjoint from its own
    train range and from all other validation ranges."""
    for w in windows:
        if w.validate_start <= w.train_end:
            raise ValueError(f"leakage: validation overlaps train in {w}")
    spans = sorted((w.validate_start, w.validate_end) for w in windows)
    for (s1, e1), (s2, _e2) in pairwise(spans):
        if s2 <= e1:
            raise ValueError(f"overlapping validation windows: {(s1, e1)} and {(s2, _e2)}")
