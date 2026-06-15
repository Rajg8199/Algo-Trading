"""Console (dashboard) read endpoints. camelCase contracts mirror
dashboard/src/lib/api/types.ts exactly — that file is the consumer contract.

Read-only by construction: no mutation, no trading, no broker calls.
Failure stance: data-absent returns empty/null with 200 (the dashboard
renders empty states); unknown run_ids return 404 (the dashboard falls back
to badged mocks). Each endpoint carries a small in-process TTL cache sized
to its data cadence so polling clients never amplify load on TimescaleDB.
"""

import csv
import json
import time as time_mod
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from tp_research.burnin import overall, run_checks

from tp_api.deps import AppState, get_state
from tp_core.timeutils import IST, now_ist

router = APIRouter(prefix="/api/v1")
State = Annotated[AppState, Depends(get_state)]

DATALAKE = Path("datalake")
UNDERLYINGS = ("NIFTY", "SENSEX")


# ── tiny TTL cache ───────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float) -> Any | None:
    hit = _cache.get(key)
    if hit and time_mod.monotonic() - hit[0] < ttl:
        return hit[1]
    return None


def _store[T](key: str, value: T) -> T:
    _cache[key] = (time_mod.monotonic(), value)
    return value


# ── 1. ops summary ───────────────────────────────────────────────────────────
_SUMMARY_SQL = text("""
    SELECT
      (SELECT max(ts) FROM ticks)        AS last_tick,
      (SELECT max(ts) FROM option_chain) AS last_chain,
      (SELECT count(*) FROM ticks        WHERE ts > now() - interval '5 minutes') AS ticks_5m,
      (SELECT count(*) FROM option_chain WHERE ts > now() - interval '5 minutes') AS chain_5m,
      (SELECT count(*) FROM data_gaps WHERE NOT resolved) AS open_gaps
""")

_TODAY_SQL = text("""
    SELECT i.underlying,
           count(*) FILTER (WHERE src = 't') AS ticks,
           count(*) FILTER (WHERE src = 'c') AS chain
    FROM (
      SELECT instrument_id, 't' AS src FROM ticks WHERE ts >= :day_start
      UNION ALL
      SELECT instrument_id, 'c' FROM option_chain WHERE ts >= :day_start
    ) x JOIN instruments i USING (instrument_id)
    WHERE i.underlying = ANY(:unders) GROUP BY 1
""")

_HEALTH_PORTS = {"recorder": 8001, "scheduler": 8002, "telegram": 8003}


async def _probe_services() -> dict[str, bool]:
    """Liveness of sibling daemons via their /health endpoints. Tries the
    docker service name first, then localhost (dev). Unreachable = down."""
    out: dict[str, bool] = {}
    async with httpx.AsyncClient(timeout=1.5) as client:
        for name, port in _HEALTH_PORTS.items():
            ok = False
            for host in (name, "localhost"):
                try:
                    response = await client.get(f"http://{host}:{port}/health")
                    ok = response.status_code == 200
                    break
                except httpx.HTTPError:
                    continue
            out[name] = ok
    return out


@router.get("/ops/summary")
async def ops_summary(state: State) -> dict[str, Any]:
    cached = _cached("ops_summary", 10)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    day_start = datetime.combine(now_ist().date(), time(0, 0), tzinfo=IST)
    async with state.db.session() as s:
        row = (await s.execute(_SUMMARY_SQL)).one()
        today = (
            await s.execute(_TODAY_SQL, {"day_start": day_start, "unders": list(UNDERLYINGS)})
        ).all()
    services = await _probe_services()
    token = await state.auth.current_token()
    ticks_today = dict.fromkeys(UNDERLYINGS, 0)
    chain_today = dict.fromkeys(UNDERLYINGS, 0)
    for underlying, ticks, chain in today:
        ticks_today[underlying] = int(ticks)
        chain_today[underlying] = int(chain)
    return _store(
        "ops_summary",
        {
            "services": {
                **services,
                "api": True,
                "db": await state.db.ping(),
                "redis": await state.bus.ping(),
            },
            "lastTick": row.last_tick.isoformat() if row.last_tick else None,
            "lastChainSnapshot": row.last_chain.isoformat() if row.last_chain else None,
            "ticksLast5m": int(row.ticks_5m),
            "chainRowsLast5m": int(row.chain_5m),
            "openDataGaps": int(row.open_gaps),
            "upstoxToken": "valid" if token else "missing/expired",
            "ticksToday": ticks_today,
            "chainRowsToday": chain_today,
        },
    )


# ── 2. DQ checks ─────────────────────────────────────────────────────────────
@router.get("/ops/dq")
async def ops_dq(state: State, days: int = Query(default=7, ge=1, le=90)) -> list[dict[str, Any]]:
    key = f"dq:{days}"
    cached = _cached(key, 60)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    cutoff = now_ist().date() - timedelta(days=days)
    async with state.db.session() as s:
        rows = (
            await s.execute(
                text("""SELECT check_date, check_name, passed, details FROM dq_checks
                        WHERE check_date > :cutoff
                        ORDER BY check_date DESC, passed, check_name"""),
                {"cutoff": cutoff},
            )
        ).all()
    return _store(
        key,
        [
            {
                "checkDate": r.check_date.isoformat(),
                "checkName": r.check_name,
                "passed": r.passed,
                "details": r.details or {},
            }
            for r in rows
        ],
    )


# ── 3. burn-in board ─────────────────────────────────────────────────────────
def _last_trading_days(n: int) -> list[date]:
    days: list[date] = []
    cursor = now_ist().date()
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


@router.get("/ops/burnin")
async def ops_burnin(state: State) -> list[dict[str, Any]]:
    cached = _cached("burnin", 300)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    out: list[dict[str, Any]] = []
    today = now_ist().date()
    for i, day in enumerate(_last_trading_days(10), start=1):
        if day == today and now_ist().hour < 21:
            out.append({"day": i, "date": day.isoformat(), "status": "PENDING", "grades": []})
            continue
        grades = await run_checks(state.db, day)
        out.append(
            {
                "day": i,
                "date": day.isoformat(),
                "status": overall(grades),
                "grades": [
                    {"name": g.name, "status": g.status, "detail": g.detail} for g in grades
                ],
            }
        )
    return _store("burnin", out)


# ── 4. feature series ────────────────────────────────────────────────────────
@router.get("/features")
async def features(
    state: State,
    name: str = Query(...),
    entity: str = Query(default="NIFTY"),
    days: int = Query(default=365, ge=1, le=2000),
) -> dict[str, Any]:
    key = f"feat:{name}:{entity}:{days}"
    cached = _cached(key, 60)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    async with state.db.session() as s:
        rows = (
            await s.execute(
                text("""SELECT ts, value FROM feature_values
                        WHERE feature_name = :name AND entity = :entity
                          AND value IS NOT NULL AND ts > now() - make_interval(days => :days)
                        ORDER BY ts"""),
                {"name": name, "entity": entity, "days": days},
            )
        ).all()
    return _store(
        key,
        {
            "featureName": name,
            "entity": entity,
            "points": [{"ts": ts.isoformat(), "value": float(v)} for ts, v in rows],
        },
    )


# ── 5 + 6. experiments ───────────────────────────────────────────────────────
def _experiment_summary(r: Any) -> dict[str, Any]:
    metrics = r.metrics or {}
    return {
        "runId": str(r.run_id),
        "hypothesis": r.hypothesis,
        "strategy": r.strategy,
        "kind": r.kind,
        "trialNumber": r.trial_number,
        "decision": metrics.get("decision"),
        "dsr": metrics.get("dsr"),
        "createdAt": r.created_at.isoformat(),
        "gitSha": r.git_sha,
    }


@router.get("/experiments")
async def experiments(state: State) -> list[dict[str, Any]]:
    cached = _cached("experiments", 30)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    async with state.db.session() as s:
        rows = (
            await s.execute(text("SELECT * FROM experiments ORDER BY created_at DESC LIMIT 200"))
        ).all()
    return _store("experiments", [_experiment_summary(r) for r in rows])


def _load_summary_artifact(artifacts_path: str | None) -> dict[str, Any]:
    if not artifacts_path:
        return {}
    candidate = Path(artifacts_path) / "summary.json"
    if not candidate.is_file():
        return {}
    try:
        return json.loads(candidate.read_text())  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return {}


def _scenario(metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metrics:
        return None
    return {
        "netPnl": metrics.get("net_pnl"),
        "sharpe": metrics.get("sharpe"),
        "profitFactor": metrics.get("profit_factor"),
        "expectancy": metrics.get("expectancy"),
        "maxDrawdownPct": metrics.get("max_drawdown_pct"),
        "winRate": metrics.get("win_rate"),
        "nTrades": metrics.get("n_trades"),
        "nDays": metrics.get("n_days"),
        "totalCosts": metrics.get("total_costs"),
    }


@router.get("/experiments/{run_id}")
async def experiment_detail(state: State, run_id: str) -> dict[str, Any]:
    async with state.db.session() as s:
        row = (
            await s.execute(text("SELECT * FROM experiments WHERE run_id = :rid"), {"rid": run_id})
        ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    summary = _load_summary_artifact(row.artifacts_path)
    artifact_metrics = summary.get("oos_metrics") or summary.get("metrics") or {}
    mc = summary.get("monte_carlo") or {}
    return {
        **_experiment_summary(row),
        "params": row.params or {},
        "gates": summary.get("gates", []),
        "metrics": {
            "expected": _scenario(
                artifact_metrics.get("EXPECTED") or artifact_metrics.get("expected")
            ),
            "best": _scenario(artifact_metrics.get("BEST") or artifact_metrics.get("best")),
            "worst": _scenario(artifact_metrics.get("WORST") or artifact_metrics.get("worst")),
        },
        "monteCarlo": (
            {
                "maxDdP95": mc.get("max_dd_p95"),
                "maxDdP99": mc.get("max_dd_p99"),
                "maxDdP999": mc.get("max_dd_p999"),
                "riskOfRuin": mc.get("risk_of_ruin"),
                "probNegativePnl": mc.get("prob_negative_pnl"),
            }
            if mc
            else None
        ),
        "regimeSharpes": summary.get("regime_sharpes", {}),
        "reasons": summary.get("reasons", []),
        "screen": bool(summary.get("screen", False)),
        "entryFunnel": [
            {"label": s.get("label"), "days": s.get("days")}
            for s in summary.get("entry_funnel", [])
        ],
    }


# ── 7 + 8. backtest artifacts ────────────────────────────────────────────────
def _trades_csv(run_id: str) -> Path | None:
    base = DATALAKE / "backtests" / run_id
    for name in ("trades_expected.csv", "trades.csv"):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def _read_trades(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        return [
            {
                "ts": r["ts"],
                "instrumentId": int(r["instrument_id"]),
                "side": r["side"],
                "qty": int(r["qty"]),
                "price": float(r["price"]),
                "costs": float(r["costs"]),
                "tag": r["tag"],
                "realizedPnl": float(r["realized_pnl"]),
            }
            for r in csv.DictReader(f)
        ]


def equity_from_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Realized-PnL equity curve derived from the trade log (daily steps).
    Realized-only by construction: intraday unrealized marks are not in the
    artifacts; this is the honest reconstruction, not an approximation of one.
    """
    by_day: dict[str, float] = defaultdict(float)
    for t in trades:
        by_day[t["ts"][:10]] += t["realizedPnl"] - t["costs"]
    points: list[dict[str, Any]] = []
    equity = 0.0
    peak = 0.0
    for day in sorted(by_day):
        equity += by_day[day]
        peak = max(peak, equity)
        points.append({"ts": day, "equity": round(equity, 2), "drawdown": round(peak - equity, 2)})
    return points


@router.get("/backtests/{run_id}/trades")
async def backtest_trades(run_id: str) -> list[dict[str, Any]]:
    path = _trades_csv(run_id)
    if path is None:
        raise HTTPException(status_code=404, detail="no trade artifacts for run_id")
    return _read_trades(path)


@router.get("/backtests/{run_id}/equity")
async def backtest_equity(run_id: str) -> list[dict[str, Any]]:
    path = _trades_csv(run_id)
    if path is None:
        raise HTTPException(status_code=404, detail="no trade artifacts for run_id")
    return equity_from_trades(_read_trades(path))


# ── paper trading lab ────────────────────────────────────────────────────────
@router.get("/paper/leaderboard")
async def paper_leaderboard(state: State) -> list[dict[str, Any]]:
    cached = _cached("paper_lb", 60)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    async with state.db.session() as s:
        rows = (
            await s.execute(
                text("""SELECT strategy, sum(net_pnl) AS pnl, count(*) AS days,
                               count(*) FILTER (WHERE net_pnl > 0) AS up_days,
                               sum(n_trades) AS trades
                        FROM pnl_daily WHERE mode = 'PAPER'
                        GROUP BY strategy ORDER BY pnl DESC""")
            )
        ).all()
    return _store(
        "paper_lb",
        [
            {
                "strategy": r.strategy,
                "netPnl": float(r.pnl or 0),
                "days": int(r.days),
                "dayWinRate": (int(r.up_days) / int(r.days)) if r.days else None,
                "trades": int(r.trades or 0),
            }
            for r in rows
        ],
    )


@router.get("/paper/signals")
async def paper_signals(
    state: State, limit: int = Query(default=50, ge=1, le=500)
) -> list[dict[str, Any]]:
    async with state.db.session() as s:
        rows = (
            await s.execute(
                text("""SELECT o.order_id, o.strategy, o.side, o.qty, o.created_at,
                               o.signal_snapshot, f.price, f.slippage
                        FROM orders o LEFT JOIN fills f USING (order_id)
                        WHERE o.mode = 'PAPER'
                        ORDER BY o.created_at DESC LIMIT :n"""),
                {"n": limit},
            )
        ).all()
    return [
        {
            "orderId": str(r.order_id),
            "strategy": r.strategy,
            "side": r.side,
            "qty": r.qty,
            "createdAt": r.created_at.isoformat(),
            "snapshot": r.signal_snapshot or {},
            "price": float(r.price) if r.price is not None else None,
            "slippage": float(r.slippage) if r.slippage is not None else None,
        }
        for r in rows
    ]


# ── option chain (live ladder) ───────────────────────────────────────────────
_CHAIN_SQL = text("""
    WITH snap AS (
        SELECT max(oc.ts) AS snap_ts
        FROM option_chain oc JOIN instruments i USING (instrument_id)
        WHERE i.underlying = :u AND oc.ts > now() - interval '1 day'
    )
    SELECT i.expiry, i.strike, i.option_type, oc.iv, oc.oi, oc.oi_prev_day,
           oc.ltp, oc.delta, oc.spot, snap.snap_ts
    FROM option_chain oc JOIN instruments i USING (instrument_id)
    JOIN snap ON oc.ts = snap.snap_ts
    WHERE i.underlying = :u AND i.option_type IS NOT NULL
""")


def _leg(r: Any) -> dict[str, Any]:
    oi = int(r["oi"]) if r["oi"] is not None else None
    oi_prev = int(r["oi_prev_day"]) if r["oi_prev_day"] is not None else None
    return {
        "iv": float(r["iv"]) if r["iv"] is not None else None,
        "oi": oi,
        "oiChg": (oi - oi_prev) if oi is not None and oi_prev is not None else None,
        "ltp": float(r["ltp"]) if r["ltp"] is not None else None,
        "delta": float(r["delta"]) if r["delta"] is not None else None,
    }


@router.get("/options/chain")
async def option_chain(
    state: State, underlying: str = Query(default="NIFTY")
) -> dict[str, Any]:
    """Latest recorded chain ladder for the underlying's nearest expiry."""
    key = f"chain:{underlying}"
    hit: dict[str, Any] | None = _cached(key, 30.0)
    if hit is not None:
        return hit
    async with state.db.session() as s:
        rows = (await s.execute(_CHAIN_SQL, {"u": underlying})).mappings().all()
    if not rows:
        return _store(key, {"underlying": underlying, "ts": None, "spot": None,
                            "expiry": None, "rows": []})
    nearest = min(r["expiry"] for r in rows if r["expiry"] is not None)
    spot = next((float(r["spot"]) for r in rows if r["spot"] is not None), None)
    ts = rows[0]["snap_ts"]
    ladder: dict[float, dict[str, Any]] = {}
    for r in rows:
        if r["expiry"] != nearest or r["strike"] is None:
            continue
        st = float(r["strike"])
        slot = ladder.setdefault(st, {"strike": st, "call": None, "put": None})
        slot["call" if r["option_type"] == "CE" else "put"] = _leg(r)
    out_rows = [ladder[k] for k in sorted(ladder)]
    return _store(key, {
        "underlying": underlying,
        "ts": ts.isoformat() if ts else None,
        "spot": spot,
        "expiry": nearest.isoformat(),
        "rows": out_rows,
    })


# ── scalp forward-test review ────────────────────────────────────────────────
_SCALP_SQL = text("""
    SELECT ts, underlying, timeframe, side, entry, stop, target, outcome, r_multiple
    FROM scalp_signals
    WHERE ts > now() - make_interval(days => :days)
    ORDER BY ts DESC
""")


def _review_dict(stats: Any) -> dict[str, Any]:
    return {
        "n": stats.n,
        "wins": stats.wins,
        "losses": stats.losses,
        "open": stats.open,
        "hitRate": stats.hit_rate,
        "expectancyR": stats.expectancy_r,
    }


@router.get("/scalp/review")
async def scalp_review_endpoint(
    state: State, days: int = Query(default=30, ge=1, le=120)
) -> dict[str, Any]:
    """Forward-test scorecard for the (UNVALIDATED) scalp engine."""
    from tp_research.scalp import summarize_review

    hit: dict[str, Any] | None = _cached(f"scalp:{days}", 60.0)
    if hit is not None:
        return hit
    async with state.db.session() as s:
        rows = (await s.execute(_SCALP_SQL, {"days": days})).mappings().all()

    graded = [(r["outcome"], float(r["r_multiple"])) for r in rows
              if r["outcome"] and r["r_multiple"] is not None]
    by_tf: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        if r["outcome"] and r["r_multiple"] is not None:
            by_tf.setdefault(r["timeframe"], []).append((r["outcome"], float(r["r_multiple"])))

    result = {
        "days": days,
        "overall": _review_dict(summarize_review(graded)),
        "byTimeframe": [
            {"timeframe": tf, **_review_dict(summarize_review(v))}
            for tf, v in sorted(by_tf.items())
        ],
        "recent": [
            {
                "ts": r["ts"].isoformat(),
                "underlying": r["underlying"],
                "timeframe": r["timeframe"],
                "side": r["side"],
                "entry": float(r["entry"]),
                "stop": float(r["stop"]),
                "target": float(r["target"]),
                "outcome": r["outcome"],
                "rMultiple": float(r["r_multiple"]) if r["r_multiple"] is not None else None,
            }
            for r in rows[:40]
        ],
    }
    return _store(f"scalp:{days}", result)
