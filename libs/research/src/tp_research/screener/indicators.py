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


def ema(values: Sequence[float], n: int) -> float | None:
    """Exponential moving average of the whole series (seeded with the first
    value). None if there aren't at least n points."""
    if n <= 0 or len(values) < n:
        return None
    k = 2.0 / (n + 1.0)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1.0 - k)
    return e


def rsi(closes: Sequence[float], n: int) -> float | None:
    """Simple-average RSI over the last n changes (Connors-style short RSI is the
    intended use). 100 when there are no losses in the window."""
    if n <= 0 or len(closes) < n + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        change = closes[i] - closes[i - 1]
        if change >= 0:
            gains += change
        else:
            losses += -change
    avg_loss = losses / n
    if avg_loss == 0:
        return 100.0
    rs = (gains / n) / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


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
