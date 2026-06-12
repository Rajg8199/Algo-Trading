from decimal import Decimal

from tp_backtest.costs import option_trade_costs
from tp_backtest.fills import FillScenario, fill_price, latency_snapshots

from tp_core.models import OrderSide
from tp_core.strategy import Quote


def test_sell_costs_include_stt_not_stamp() -> None:
    costs = option_trade_costs(OrderSide.SELL, Decimal("100"), 75, "NSE")
    assert costs.stt == Decimal("7.50")  # 0.1% of 7500
    assert costs.stamp == 0
    assert costs.brokerage == Decimal("20")
    assert costs.total > Decimal("30")


def test_buy_costs_include_stamp_not_stt() -> None:
    costs = option_trade_costs(OrderSide.BUY, Decimal("100"), 75, "NSE")
    assert costs.stt == 0
    assert costs.stamp == Decimal("0.23")  # 0.003% of 7500
    # GST = 18% of (brokerage + exchange + sebi), computed on unrounded
    # components: 18% x (20 + 2.62725 + 0.0075) = 4.074255 -> 4.07
    assert costs.gst == Decimal("4.07")


def test_bse_exchange_rate_differs() -> None:
    nse = option_trade_costs(OrderSide.SELL, Decimal("100"), 75, "NSE")
    bse = option_trade_costs(OrderSide.SELL, Decimal("100"), 75, "BSE")
    assert nse.exchange != bse.exchange


QUOTE = Quote(instrument_id=1, ltp=100.0, bid=99.0, ask=101.0)


def test_best_case_fills_at_mid_no_latency() -> None:
    fill = fill_price(QUOTE, OrderSide.BUY, FillScenario.BEST)
    assert fill is not None
    assert fill.price == Decimal("100.0")
    assert latency_snapshots(FillScenario.BEST) == 0


def test_expected_crosses_spread_with_multiplier() -> None:
    fill = fill_price(QUOTE, OrderSide.BUY, FillScenario.EXPECTED)
    assert fill is not None
    # ask 101 + 0.5xhalf-spread(1) = 101.5
    assert fill.price == Decimal("101.5")
    assert latency_snapshots(FillScenario.EXPECTED) == 1


def test_worst_case_is_worse_than_expected() -> None:
    expected = fill_price(QUOTE, OrderSide.SELL, FillScenario.EXPECTED)
    worst = fill_price(QUOTE, OrderSide.SELL, FillScenario.WORST)
    assert expected is not None and worst is not None
    assert worst.price < expected.price  # selling: worse = lower


def test_missing_opposite_quote_means_no_fill() -> None:
    no_bid = Quote(instrument_id=1, ltp=100.0, bid=None, ask=101.0)
    assert fill_price(no_bid, OrderSide.SELL, FillScenario.EXPECTED) is None
    # BEST still fills at mid-fallback (ltp) — by design, to expose the gap
    assert fill_price(no_bid, OrderSide.SELL, FillScenario.BEST) is not None
