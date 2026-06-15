"""Pure indicator helpers over plain float sequences. No pandas — the windows
are short and the call sites are explicit, which keeps the math auditable and
mypy-strict clean. Every function returns None when it lacks enough data rather
than guessing."""

from __future__ import annotations

from collections.abc import Sequence


def sma(values: Sequence[float], n: int) -> float | None:
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / n


def highest(values: Sequence[float], n: int) -> float | None:
    if n <= 0 or len(values) < n:
        return None
    return max(values[-n:])


def lowest(values: Sequence[float], n: int) -> float | None:
    if n <= 0 or len(values) < n:
        return None
    return min(values[-n:])


def true_ranges(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    """TR_t = max(H-L, |H-prevC|, |L-prevC|). The first bar has no prior close,
    so its TR is just its range."""
    out: list[float] = []
    for i in range(len(highs)):
        if i == 0:
            out.append(highs[i] - lows[i])
            continue
        prev_close = closes[i - 1]
        out.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        )
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], n: int
) -> float | None:
    """Average True Range over the last n bars (simple mean of TR — stable and
    deterministic; the smoothing choice is immaterial at swing horizons)."""
    if n <= 0 or len(highs) < n + 1:
        return None
    tr = true_ranges(highs, lows, closes)
    window = tr[-n:]
    return sum(window) / n
