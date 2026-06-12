from tp_api.routers.console import _scenario, equity_from_trades


def trade(ts: str, pnl: float, costs: float = 40.0) -> dict[str, object]:
    return {
        "ts": ts,
        "instrumentId": 1,
        "side": "SETTLE",
        "qty": 75,
        "price": 0.0,
        "costs": costs,
        "tag": "SETTLE",
        "realizedPnl": pnl,
    }


def test_equity_from_trades_daily_steps_and_drawdown() -> None:
    trades = [
        trade("2026-06-10T15:25:00", 5000.0),
        trade("2026-06-10T15:25:00", 1000.0),
        trade("2026-06-11T15:25:00", -3000.0),
        trade("2026-06-12T15:25:00", 4000.0),
    ]
    points = equity_from_trades(trades)
    assert [p["ts"] for p in points] == ["2026-06-10", "2026-06-11", "2026-06-12"]
    assert points[0]["equity"] == 5920.0  # 6000 - 2*40
    assert points[1]["equity"] == 2880.0  # -3000 - 40
    assert points[1]["drawdown"] == 3040.0  # peak 5920 - 2880
    assert points[2]["drawdown"] == 0.0  # new high? 2880+3960=6840 > 5920


def test_equity_empty_trades() -> None:
    assert equity_from_trades([]) == []


def test_scenario_mapping() -> None:
    out = _scenario({"net_pnl": 100.0, "sharpe": 1.5, "max_drawdown_pct": 4.2, "n_trades": 10})
    assert out is not None
    assert out["netPnl"] == 100.0
    assert out["maxDrawdownPct"] == 4.2
    assert out["profitFactor"] is None  # absent key -> null, never invented
    assert _scenario(None) is None
    assert _scenario({}) is None
