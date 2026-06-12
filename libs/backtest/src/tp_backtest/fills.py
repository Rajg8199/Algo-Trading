"""Fill models. Three named scenarios; a strategy is reported under all
three and judged on EXPECTED and WORST — best case exists only to show the
gap, never to justify a strategy.

  BEST      mid-price fill, zero latency, 1.0x slippage scenario
  EXPECTED  cross the spread (buy at ask / sell at bid), one-snapshot
            latency (decision at t fills at the NEXT snapshot, ~60s),
            1.5x slippage multiplier on the half-spread
  WORST     cross the spread + 2.0x multiplier, one-snapshot latency

Slippage definition: half-spread x (multiplier - 1) beyond the touched side.
Deterministic by construction — no random slippage, no luck in either
direction. Missing quotes (no bid for a sell, no ask for a buy) mean NO FILL,
which is itself a research result: strategies needing fills that don't exist
are rejected by reality before statistics.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from tp_core.models import OrderSide
from tp_core.strategy import Quote


class FillScenario(StrEnum):
    BEST = "BEST"
    EXPECTED = "EXPECTED"
    WORST = "WORST"


SCENARIO_PARAMS: dict[FillScenario, tuple[bool, float, int]] = {
    # (cross_spread, slippage_multiplier, latency_snapshots)
    FillScenario.BEST: (False, 1.0, 0),
    FillScenario.EXPECTED: (True, 1.5, 1),
    FillScenario.WORST: (True, 2.0, 1),
}


@dataclass(frozen=True)
class FillResult:
    price: Decimal
    slippage_vs_mid: Decimal


def latency_snapshots(scenario: FillScenario) -> int:
    return SCENARIO_PARAMS[scenario][2]


def fill_price(
    quote: Quote,
    side: OrderSide,
    scenario: FillScenario,
    synthetic_spread_pct: float | None = None,
) -> FillResult | None:
    """Price for one fill from the quote at the (latency-adjusted) snapshot.

    synthetic_spread_pct (registered amendment for imported vendor bars that
    carry no quotes): when the opposing quote is missing AND this is set, a
    synthetic touch is derived as mid +/- max(0.05, mid * pct/100 / 2).
    Default None preserves the no-quote => no-fill contract for recorded data.
    """
    cross, multiplier, _ = SCENARIO_PARAMS[scenario]
    mid = quote.mid
    if mid is None:
        return None

    if not cross:
        price = Decimal(str(round(mid, 2)))
        return FillResult(price=price, slippage_vs_mid=Decimal(0))

    touch = quote.ask if side is OrderSide.BUY else quote.bid
    if touch is None and synthetic_spread_pct is not None:
        half = max(0.05, mid * synthetic_spread_pct / 200.0)
        touch = mid + half if side is OrderSide.BUY else mid - half
    if touch is None:
        return None  # no opposing quote: unfillable, not "fill at ltp"

    half_spread = abs(touch - mid)
    extra = half_spread * (multiplier - 1.0)
    raw = touch + extra if side is OrderSide.BUY else touch - extra
    if raw <= 0:
        return None
    price = Decimal(str(round(raw, 2)))
    slip = Decimal(str(round(abs(raw - mid), 4)))
    return FillResult(price=price, slippage_vs_mid=slip)
