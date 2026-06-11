from decimal import Decimal

from tp_upstox.feed import parse_feed_message

FULL_MESSAGE = {
    "feeds": {
        "NSE_FO|54452": {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 152.35, "ltt": "1718082600000"},
                    "marketLevel": {
                        "bidAskQuote": [
                            {"bidQ": "75", "bidP": 152.3, "askQ": "150", "askP": 152.45}
                        ]
                    },
                    "vtt": "1250000",
                    "oi": "5400000",
                }
            }
        },
        "NSE_INDEX|Nifty 50": {"fullFeed": {"indexFF": {"ltpc": {"ltp": 24512.4}}}},
    }
}


def test_parses_market_full_feed() -> None:
    quotes = {q.upstox_key: q for q in parse_feed_message(FULL_MESSAGE)}
    opt = quotes["NSE_FO|54452"]
    assert opt.ltp == Decimal("152.35")
    assert opt.bid == Decimal("152.3")
    assert opt.ask == Decimal("152.45")
    assert opt.bid_qty == 75
    assert opt.oi == 5400000


def test_parses_index_feed_without_depth() -> None:
    quotes = {q.upstox_key: q for q in parse_feed_message(FULL_MESSAGE)}
    idx = quotes["NSE_INDEX|Nifty 50"]
    assert idx.ltp == Decimal("24512.4")
    assert idx.bid is None


def test_ltpc_only_fallback() -> None:
    msg = {"feeds": {"K": {"ltpc": {"ltp": 10.5}}}}
    (quote,) = parse_feed_message(msg)
    assert quote.ltp == Decimal("10.5")


def test_tolerates_garbage() -> None:
    assert parse_feed_message({}) == []
    assert parse_feed_message({"feeds": {"K": {}}}) == []
    assert parse_feed_message({"feeds": {"K": {"fullFeed": {"marketFF": {"ltpc": {}}}}}}) == []
