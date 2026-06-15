"""EXP-001-EOD unblock: ConditionalVRP must be able to act on the single
15:30 settlement snapshot of bhavcopy data. The default decision window
(15:18-15:24, intraday 001) must still REJECT 15:30; a widened window must
admit it. Everything else about the strategy is unchanged.
"""

from datetime import date, datetime, time

from tp_backtest.strategies.vrp import ConditionalVRP, VRPParams

from tp_core.strategy import InstrumentMeta, MarketState, Quote
from tp_core.timeutils import IST

TRADE_DAY = date(2026, 6, 12)
EXPIRY = date(2026, 6, 16)  # DTE 4, inside [2, 5]
LOT = 65

# A condor-able chain: 25-delta shorts and 10-delta wings, both CE and PE,
# all with priceable mids (ltp only — exactly like bhavcopy, no bid/ask).
_LEGS = {
    1: (InstrumentMeta(1, "NIFTY", "OPT", EXPIRY, 24700.0, "CE", LOT), 0.25, 90.0),
    2: (InstrumentMeta(2, "NIFTY", "OPT", EXPIRY, 24300.0, "PE", LOT), -0.25, 88.0),
    3: (InstrumentMeta(3, "NIFTY", "OPT", EXPIRY, 25200.0, "CE", LOT), 0.10, 30.0),
    4: (InstrumentMeta(4, "NIFTY", "OPT", EXPIRY, 23800.0, "PE", LOT), -0.10, 28.0),
}
_META = {iid: m for iid, (m, _, _) in _LEGS.items()}
_QUOTES = {iid: Quote(iid, ltp, None, None, delta=d) for iid, (_, d, ltp) in _LEGS.items()}

# Features that pass every conditional filter (yesterday's values, by policy).
_FEATURES = {
    "NIFTY": {
        "atm_iv_front": 16.0,
        "har_rv_forecast_1d": 11.0,  # VRP = 5.0 vol points, >= min 2.0
        "iv_percentile_1y": 80.0,
        "vov_20d": 0.8,
        "term_slope": 0.5,
    }
}


def _state_at(hh: int, mm: int) -> MarketState:
    return MarketState(
        ts=datetime.combine(TRADE_DAY, time(hh, mm), tzinfo=IST),
        spot={"NIFTY": 24500.0},
        quotes=dict(_QUOTES),
        meta=_META,
        features=_FEATURES,
    )


def test_default_window_rejects_eod_snapshot() -> None:
    strat = ConditionalVRP(VRPParams())  # default 15:18-15:24
    assert strat.on_market(_state_at(15, 30)) == []  # 15:30 is outside the window


def test_default_window_still_enters_intraday() -> None:
    strat = ConditionalVRP(VRPParams())
    intents = strat.on_market(_state_at(15, 20))  # inside default window
    assert len(intents) == 4  # short CE + short PE + two wings


def test_widened_window_enters_at_eod_settlement() -> None:
    params = VRPParams(decision_start=time(15, 25), decision_end=time(15, 35))
    strat = ConditionalVRP(params)
    intents = strat.on_market(_state_at(15, 30))  # the bhavcopy settlement snapshot
    assert len(intents) == 4
    legs = {i.signal_snapshot["leg"] for i in intents}
    assert any("SELL_CE" in leg for leg in legs) and any("BUY_PE" in leg for leg in legs)
