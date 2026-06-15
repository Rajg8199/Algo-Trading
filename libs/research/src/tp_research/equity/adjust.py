"""Split / bonus back-adjustment for daily equity bars.

NSE bhavcopy prices are RAW: a 1:2 split or 1:1 bonus shows up as a ~50%
overnight crash that isn't real, which silently corrupts breakout (fake
stop-outs) and momentum (fake -50% return -> wrong ranking). We have no clean
free corporate-actions feed, so we detect splits/bonuses from the data: an
overnight open/prev-close ratio that sits very close to the reciprocal of a
known ratio (1/2, 1/3, 1/5, …). A genuine 30 %+ gap almost never lands exactly
on 0.5000 or 0.2000, so the "near a known factor" test is the safeguard.

Back-adjustment is the standard ratio method: divide all PRE-event prices by the
factor and multiply pre-event volume by it, making the series continuous in
today's share terms. Raw rows stay untouched in the DB — this runs on read.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from tp_research.screener.models import DailyBar

# Common Indian split/bonus factors (price divides by these). 1.5 = 3:2 bonus.
KNOWN_FACTORS = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 10.0)
_TOLERANCE = 0.04  # ratio must be within 4% of 1/factor
_MIN_GAP = 0.20  # only consider overnight moves beyond ±20% as adjustment candidates


def detect_factor(prev_close: float, today_open: float) -> float | None:
    """Return the split/bonus factor if the overnight move matches one, else
    None. factor f means the price fell to ~1/f (e.g. 1:2 split → f=2)."""
    if prev_close <= 0 or today_open <= 0:
        return None
    ratio = today_open / prev_close
    if ratio >= 1 - _MIN_GAP:  # not a big-enough down gap to be a split/bonus
        return None
    for f in KNOWN_FACTORS:
        if abs(ratio - 1.0 / f) <= _TOLERANCE * (1.0 / f):
            return f
    return None


def adjust_splits(bars: Sequence[DailyBar]) -> list[DailyBar]:
    """Back-adjust a single symbol's chronological bars for detected splits/
    bonuses. Returns a new list; input is untouched."""
    if len(bars) < 2:
        return list(bars)

    # Find split days (index i = first post-split bar) and their factors.
    events: list[tuple[int, float]] = []
    for i in range(1, len(bars)):
        factor = detect_factor(bars[i - 1].close, bars[i].open)
        if factor is not None:
            events.append((i, factor))
    if not events:
        return list(bars)

    # Cumulative factor applied to bars strictly before each event: walking
    # backwards, every bar before event i is divided by that event's factor.
    out = list(bars)
    cum = 1.0
    next_event = len(events) - 1
    for i in range(len(out) - 1, -1, -1):
        while next_event >= 0 and i < events[next_event][0]:
            cum *= events[next_event][1]
            next_event -= 1
        if cum != 1.0:
            b = out[i]
            out[i] = replace(
                b,
                open=b.open / cum,
                high=b.high / cum,
                low=b.low / cum,
                close=b.close / cum,
                volume=b.volume * cum,
            )
    return out
