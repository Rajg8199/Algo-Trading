"""Data validation rules. Each check is one SQL query + a threshold judgment.

Severity semantics:
  P1 — the day's data is unusable for research until investigated
  P2 — degraded quality; research can proceed with awareness

Thresholds live next to the checks they govern; tuning them is a code change
with review, not a config tweak — silent threshold drift is how bad data
sneaks into research.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import text

from tp_core.db import Database
from tp_core.models import Severity
from tp_core.timeutils import IST

UNDERLYINGS = ("NIFTY", "SENSEX")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    severity: Severity
    details: dict[str, Any]


CheckFn = Callable[[Database, date], Awaitable[list[CheckResult]]]


def _session_bounds(trade_date: date) -> dict[str, datetime]:
    return {
        "day_open": datetime.combine(trade_date, time(9, 15), tzinfo=IST),
        "day_close": datetime.combine(trade_date, time(15, 30), tzinfo=IST),
    }


async def _rows(db: Database, sql: str, params: dict[str, Any]) -> list[Any]:
    async with db.session() as s:
        result = await s.execute(text(sql), params)
        return list(result.all())


# ── 1. completeness ─────────────────────────────────────────────────────────
MIN_TICK_ROWS = 50_000
MIN_CHAIN_ROWS = 10_000


async def completeness(db: Database, trade_date: date) -> list[CheckResult]:
    out: list[CheckResult] = []
    for table, minimum in (("ticks", MIN_TICK_ROWS), ("option_chain", MIN_CHAIN_ROWS)):
        rows = await _rows(
            db,
            f"""SELECT i.underlying, count(*) FROM {table} t
                JOIN instruments i USING (instrument_id)
                WHERE t.ts BETWEEN :day_open AND :day_close
                  AND i.underlying = ANY(:unders)
                GROUP BY i.underlying""",
            {**_session_bounds(trade_date), "unders": list(UNDERLYINGS)},
        )
        counts = dict(rows)
        for u in UNDERLYINGS:
            n = counts.get(u, 0)
            out.append(
                CheckResult(
                    f"completeness_{table}_{u}",
                    n >= minimum,
                    Severity.P1,
                    {"rows": n, "minimum": minimum},
                )
            )
    return out


# ── 2. intraday gap detection ───────────────────────────────────────────────
MAX_CHAIN_GAP_SECONDS = 180  # 3 missed polls at 60s cadence


async def chain_gaps(db: Database, trade_date: date) -> list[CheckResult]:
    rows = await _rows(
        db,
        """WITH snaps AS (
             SELECT i.underlying, oc.ts,
                    lag(oc.ts) OVER (PARTITION BY i.underlying ORDER BY oc.ts) AS prev_ts
             FROM (SELECT DISTINCT instrument_id, ts FROM option_chain
                   WHERE ts BETWEEN :day_open AND :day_close) oc
             JOIN instruments i USING (instrument_id)
             WHERE i.underlying = ANY(:unders)
           )
           SELECT underlying,
                  coalesce(max(extract(epoch FROM ts - prev_ts)), 0) AS max_gap_s,
                  count(*) FILTER (
                    WHERE extract(epoch FROM ts - prev_ts) > :max_gap) AS n_gaps
           FROM snaps GROUP BY underlying""",
        {
            **_session_bounds(trade_date),
            "unders": list(UNDERLYINGS),
            "max_gap": MAX_CHAIN_GAP_SECONDS,
        },
    )
    return [
        CheckResult(
            f"chain_gaps_{u}",
            int(n_gaps) == 0,
            Severity.P2,
            {"max_gap_seconds": float(max_gap), "gaps_over_threshold": int(n_gaps)},
        )
        for u, max_gap, n_gaps in rows
    ]


# ── 3. missing strikes ──────────────────────────────────────────────────────
MAX_MISSING_NEAR_STRIKES_PCT = 5.0  # within ±5% of spot


async def missing_strikes(db: Database, trade_date: date) -> list[CheckResult]:
    rows = await _rows(
        db,
        """WITH latest AS (
             SELECT i.underlying, max(oc.ts) AS snap_ts
             FROM option_chain oc JOIN instruments i USING (instrument_id)
             WHERE oc.ts BETWEEN :day_open AND :day_close
               AND i.underlying = ANY(:unders)
             GROUP BY i.underlying
           ),
           snap AS (
             SELECT i.underlying, i.strike, max(oc.spot) AS spot
             FROM option_chain oc
             JOIN instruments i USING (instrument_id)
             JOIN latest l ON l.underlying = i.underlying AND oc.ts = l.snap_ts
             GROUP BY i.underlying, i.strike
           ),
           expected AS (
             SELECT i.underlying, i.strike
             FROM instruments i
             JOIN (SELECT underlying, min(expiry) AS expiry FROM instruments
                   WHERE segment='OPT' AND expiry >= :trade_date AND is_active
                   GROUP BY underlying) fe
               ON fe.underlying = i.underlying AND fe.expiry = i.expiry
             WHERE i.segment = 'OPT' AND i.underlying = ANY(:unders)
           )
           SELECT e.underlying,
                  count(*) AS expected_n,
                  count(s.strike) AS present_n
           FROM expected e
           LEFT JOIN snap s ON s.underlying = e.underlying AND s.strike = e.strike
           JOIN (SELECT underlying, avg(spot) AS spot FROM snap GROUP BY underlying) sp
             ON sp.underlying = e.underlying
           WHERE e.strike BETWEEN sp.spot * 0.95 AND sp.spot * 1.05
           GROUP BY e.underlying""",
        {**_session_bounds(trade_date), "unders": list(UNDERLYINGS), "trade_date": trade_date},
    )
    out = []
    for u, expected_n, present_n in rows:
        missing_pct = 100.0 * (expected_n - present_n) / expected_n if expected_n else 0.0
        out.append(
            CheckResult(
                f"missing_strikes_{u}",
                missing_pct <= MAX_MISSING_NEAR_STRIKES_PCT,
                Severity.P1,
                {
                    "expected": int(expected_n),
                    "present": int(present_n),
                    "missing_pct": round(missing_pct, 2),
                },
            )
        )
    return out


# ── 4. duplicate / frozen snapshots (vendor staleness) ─────────────────────
MAX_IDENTICAL_CONSECUTIVE_SNAPSHOTS = 3


async def frozen_snapshots(db: Database, trade_date: date) -> list[CheckResult]:
    """Consecutive snapshots whose aggregate (Σltp, Σoi) fingerprints are
    identical: the API serving cached data while timestamps advance."""
    rows = await _rows(
        db,
        """WITH fp AS (
             SELECT i.underlying, oc.ts,
                    sum(oc.ltp) AS ltp_sum, sum(oc.oi) AS oi_sum
             FROM option_chain oc JOIN instruments i USING (instrument_id)
             WHERE oc.ts BETWEEN :day_open AND :day_close
               AND i.underlying = ANY(:unders)
             GROUP BY i.underlying, oc.ts
           ),
           marked AS (
             SELECT underlying,
                    (ltp_sum = lag(ltp_sum) OVER w AND oi_sum = lag(oi_sum) OVER w)
                      AS is_dup
             FROM fp WINDOW w AS (PARTITION BY underlying ORDER BY ts)
           )
           SELECT underlying, count(*) FILTER (WHERE is_dup) AS dups, count(*) AS total
           FROM marked GROUP BY underlying""",
        {**_session_bounds(trade_date), "unders": list(UNDERLYINGS)},
    )
    return [
        CheckResult(
            f"frozen_snapshots_{u}",
            int(dups) <= MAX_IDENTICAL_CONSECUTIVE_SNAPSHOTS,
            Severity.P2,
            {"identical_consecutive": int(dups), "snapshots": int(total)},
        )
        for u, dups, total in rows
    ]


# ── 5. stale index ticks ────────────────────────────────────────────────────
MAX_INDEX_TICK_GAP_SECONDS = 60


async def stale_index_ticks(db: Database, trade_date: date) -> list[CheckResult]:
    rows = await _rows(
        db,
        """WITH gaps AS (
             SELECT i.underlying, extract(epoch FROM ts - lag(ts) OVER w) AS gap_s
             FROM ticks t JOIN instruments i USING (instrument_id)
             WHERE t.ts BETWEEN :day_open AND :day_close
               AND i.segment = 'INDEX' AND i.underlying = ANY(:all_unders)
             WINDOW w AS (PARTITION BY i.underlying ORDER BY ts)
           )
           SELECT underlying, coalesce(max(gap_s), 0) AS max_gap
           FROM gaps GROUP BY underlying""",
        {**_session_bounds(trade_date), "all_unders": [*UNDERLYINGS, "INDIAVIX"]},
    )
    return [
        CheckResult(
            f"stale_ticks_{u}",
            float(max_gap) <= MAX_INDEX_TICK_GAP_SECONDS,
            Severity.P2,
            {"max_gap_seconds": float(max_gap)},
        )
        for u, max_gap in rows
    ]


# ── 6 + 7. invalid greeks / invalid IV ──────────────────────────────────────
MAX_INVALID_GREEKS_PCT = 1.0
MAX_INVALID_ATM_IV_PCT = 5.0


async def invalid_greeks(db: Database, trade_date: date) -> list[CheckResult]:
    rows = await _rows(
        db,
        """SELECT i.underlying,
                  count(*) AS total,
                  count(*) FILTER (
                    WHERE abs(oc.delta) > 1 OR oc.gamma < 0 OR oc.vega < 0
                       OR (i.option_type = 'CE' AND oc.delta < -0.01)
                       OR (i.option_type = 'PE' AND oc.delta >  0.01)
                  ) AS bad
           FROM option_chain oc JOIN instruments i USING (instrument_id)
           WHERE oc.ts BETWEEN :day_open AND :day_close
             AND i.underlying = ANY(:unders) AND oc.delta IS NOT NULL
           GROUP BY i.underlying""",
        {**_session_bounds(trade_date), "unders": list(UNDERLYINGS)},
    )
    out = []
    for u, total, bad in rows:
        pct = 100.0 * bad / total if total else 0.0
        out.append(
            CheckResult(
                f"invalid_greeks_{u}",
                pct <= MAX_INVALID_GREEKS_PCT,
                Severity.P2,
                {"bad_rows": int(bad), "total": int(total), "pct": round(pct, 3)},
            )
        )
    return out


async def invalid_iv(db: Database, trade_date: date) -> list[CheckResult]:
    """IV sanity on near-ATM rows (±3% of spot) where IV must exist and be sane.
    Wings legitimately have garbage IVs; ATM does not get that excuse."""
    rows = await _rows(
        db,
        """SELECT i.underlying,
                  count(*) AS total,
                  count(*) FILTER (
                    WHERE oc.iv IS NULL OR oc.iv <= 1.0 OR oc.iv >= 200.0) AS bad
           FROM option_chain oc JOIN instruments i USING (instrument_id)
           WHERE oc.ts BETWEEN :day_open AND :day_close
             AND i.underlying = ANY(:unders)
             AND oc.spot IS NOT NULL
             AND i.strike BETWEEN oc.spot * 0.97 AND oc.spot * 1.03
           GROUP BY i.underlying""",
        {**_session_bounds(trade_date), "unders": list(UNDERLYINGS)},
    )
    out = []
    for u, total, bad in rows:
        pct = 100.0 * bad / total if total else 0.0
        out.append(
            CheckResult(
                f"invalid_iv_atm_{u}",
                pct <= MAX_INVALID_ATM_IV_PCT,
                Severity.P1,
                {"bad_rows": int(bad), "total": int(total), "pct": round(pct, 2)},
            )
        )
    return out


# ── 8. expiry consistency ───────────────────────────────────────────────────
async def expiry_consistency(db: Database, trade_date: date) -> list[CheckResult]:
    rows = await _rows(
        db,
        """SELECT count(*) FROM option_chain oc
           JOIN instruments i USING (instrument_id)
           WHERE oc.ts BETWEEN :day_open AND :day_close
             AND i.expiry < :trade_date""",
        {**_session_bounds(trade_date), "trade_date": trade_date},
    )
    n = int(rows[0][0]) if rows else 0
    return [
        CheckResult(
            "expiry_consistency",
            n == 0,
            Severity.P2,
            {"rows_for_expired_contracts": n},
        )
    ]


# ── 9. OI consistency ───────────────────────────────────────────────────────
MAX_TOTAL_OI_DAY_CHANGE_PCT = 60.0


async def oi_consistency(db: Database, trade_date: date) -> list[CheckResult]:
    """Total front-expiry OI shouldn't move >60% day-over-day except expiry
    rollover days — those are excluded by comparing same-expiry totals only."""
    rows = await _rows(
        db,
        """WITH daily AS (
             SELECT i.underlying, i.expiry, oc.ts::date AS d,
                    max(oc.ts) AS last_ts
             FROM option_chain oc JOIN instruments i USING (instrument_id)
             WHERE oc.ts BETWEEN :lookback_start AND :day_close
               AND i.underlying = ANY(:unders)
             GROUP BY i.underlying, i.expiry, oc.ts::date
           ),
           totals AS (
             SELECT d.underlying, d.expiry, d.d, sum(oc.oi) AS total_oi
             FROM daily d
             JOIN instruments i ON i.underlying = d.underlying AND i.expiry = d.expiry
             JOIN option_chain oc
               ON oc.instrument_id = i.instrument_id AND oc.ts = d.last_ts
             GROUP BY d.underlying, d.expiry, d.d
           ),
           changes AS (
             SELECT underlying, expiry, d, total_oi,
                    lag(total_oi) OVER (PARTITION BY underlying, expiry ORDER BY d)
                      AS prev_oi
             FROM totals
           )
           SELECT underlying,
                  max(abs(total_oi - prev_oi) / nullif(prev_oi, 0) * 100) AS max_chg
           FROM changes
           WHERE d = :trade_date AND prev_oi IS NOT NULL
           GROUP BY underlying""",
        {
            **_session_bounds(trade_date),
            "lookback_start": _session_bounds(trade_date)["day_open"] - timedelta(days=5),
            "unders": list(UNDERLYINGS),
            "trade_date": trade_date,
        },
    )
    return [
        CheckResult(
            f"oi_consistency_{u}",
            max_chg is None or float(max_chg) <= MAX_TOTAL_OI_DAY_CHANGE_PCT,
            Severity.P2,
            {"max_same_expiry_oi_change_pct": round(float(max_chg), 1) if max_chg else None},
        )
        for u, max_chg in rows
    ]


ALL_CHECKS: list[CheckFn] = [
    completeness,
    chain_gaps,
    missing_strikes,
    frozen_snapshots,
    stale_index_ticks,
    invalid_greeks,
    invalid_iv,
    expiry_consistency,
    oi_consistency,
]
