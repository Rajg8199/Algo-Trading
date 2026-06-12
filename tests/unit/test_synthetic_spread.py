from tp_backtest.fills import FillScenario, fill_price

from tp_core.models import OrderSide
from tp_core.strategy import Quote

QUOTELESS = Quote(instrument_id=1, ltp=100.0, bid=None, ask=None)


def test_default_behavior_unchanged_no_quote_no_fill() -> None:
    assert fill_price(QUOTELESS, OrderSide.SELL, FillScenario.EXPECTED) is None


def test_synthetic_spread_fills_quoteless_bars() -> None:
    fill = fill_price(QUOTELESS, OrderSide.SELL, FillScenario.EXPECTED, synthetic_spread_pct=1.0)
    assert fill is not None
    # mid 100, 1% spread => half 0.5, touch 99.5, expected adds 0.5x half beyond
    assert float(fill.price) == 99.25


def test_synthetic_spread_floor() -> None:
    cheap = Quote(instrument_id=1, ltp=2.0, bid=None, ask=None)
    fill = fill_price(cheap, OrderSide.BUY, FillScenario.EXPECTED, synthetic_spread_pct=1.0)
    assert fill is not None
    # half-spread floored at 0.05: touch 2.05, +0.5x half => 2.075 -> 2.07
    # (binary float round-half-even; conservative either way at this scale)
    assert float(fill.price) == 2.07


def test_real_quotes_take_precedence_over_synthetic() -> None:
    quoted = Quote(instrument_id=1, ltp=100.0, bid=99.0, ask=101.0)
    with_synth = fill_price(quoted, OrderSide.BUY, FillScenario.EXPECTED, synthetic_spread_pct=5.0)
    without = fill_price(quoted, OrderSide.BUY, FillScenario.EXPECTED)
    assert with_synth is not None and without is not None
    assert with_synth.price == without.price  # real bid/ask used, synthetic ignored
