"""Live (latest-snapshot) index-options metrics from the recorder's chain.

During market hours the recorder writes a full chain snapshot (~2-min cadence)
with per-option IV/OI and the spot. This computes a factual intraday read —
spot, ATM IV, ATM straddle, PCR, total OI — for the nearest expiry. Pure summary
is separated from the DB load so it is unit-testable. Informational only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from tp_core.db import Database

# Latest snapshot for an underlying (max ts within the last day), all expiries.
_LIVE_CHAIN_SQL = text("""
    WITH snap AS (
        SELECT max(oc.ts) AS snap_ts
        FROM option_chain oc
        JOIN instruments i USING (instrument_id)
        WHERE i.underlying = :underlying AND oc.ts > now() - interval '1 day'
    )
    SELECT i.expiry, i.strike, i.option_type, oc.iv, oc.oi, oc.ltp, oc.spot, snap.snap_ts
    FROM option_chain oc
    JOIN instruments i USING (instrument_id)
    JOIN snap ON oc.ts = snap.snap_ts
    WHERE i.underlying = :underlying AND i.option_type IS NOT NULL
""")

# Latest India VIX index level.
_VIX_SQL = text("""
    SELECT oc_ltp FROM (
        SELECT t.ltp AS oc_ltp, t.ts
        FROM ticks t JOIN instruments i USING (instrument_id)
        WHERE i.underlying = 'INDIAVIX' AND t.ts > now() - interval '1 day'
        ORDER BY t.ts DESC LIMIT 1
    ) q
""")


@dataclass
class _LiveRow:
    strike: float
    option_type: str
    iv: float | None
    oi: float | None
    ltp: float | None


@dataclass(frozen=True)
class LiveOptionsSnapshot:
    underlying: str
    ts: datetime
    spot: float
    atm_strike: float | None
    atm_iv: float | None
    atm_straddle: float | None
    pcr_oi: float | None
    total_oi: float | None


def summarize_live(
    underlying: str, ts: datetime, spot: float, rows: list[_LiveRow]
) -> LiveOptionsSnapshot:
    """`rows` must be a single expiry's chain. ATM is the strike nearest spot."""
    by_strike: dict[float, dict[str, _LiveRow]] = {}
    for r in rows:
        by_strike.setdefault(r.strike, {})[r.option_type] = r

    atm_strike = atm_iv = atm_straddle = None
    if by_strike:
        atm_strike = min(by_strike, key=lambda k: abs(k - spot))
        legs = by_strike[atm_strike]
        ce, pe = legs.get("CE"), legs.get("PE")
        if ce and pe and ce.iv and pe.iv and 1.0 < ce.iv < 200.0 and 1.0 < pe.iv < 200.0:
            atm_iv = (ce.iv + pe.iv) / 2
        if ce and pe and ce.ltp is not None and pe.ltp is not None:
            atm_straddle = ce.ltp + pe.ltp

    call_oi = sum(r.oi for r in rows if r.option_type == "CE" and r.oi)
    put_oi = sum(r.oi for r in rows if r.option_type == "PE" and r.oi)
    pcr = put_oi / call_oi if call_oi else None
    total_oi = (call_oi + put_oi) or None
    return LiveOptionsSnapshot(
        underlying, ts, spot, atm_strike, atm_iv, atm_straddle, pcr, total_oi
    )


async def load_live_snapshot(db: Database, underlying: str) -> LiveOptionsSnapshot | None:
    """Latest recorded chain for the underlying's NEAREST expiry, or None if no
    recent snapshot exists."""
    async with db.session() as s:
        records = (await s.execute(_LIVE_CHAIN_SQL, {"underlying": underlying})).mappings().all()
    if not records:
        return None
    spots = [float(r["spot"]) for r in records if r["spot"] is not None]
    if not spots:
        return None
    ts = records[0]["snap_ts"]
    nearest_expiry = min(r["expiry"] for r in records if r["expiry"] is not None)
    rows = [
        _LiveRow(
            strike=float(r["strike"]),
            option_type=str(r["option_type"]),
            iv=float(r["iv"]) if r["iv"] is not None else None,
            oi=float(r["oi"]) if r["oi"] is not None else None,
            ltp=float(r["ltp"]) if r["ltp"] is not None else None,
        )
        for r in records
        if r["expiry"] == nearest_expiry and r["strike"] is not None
    ]
    return summarize_live(underlying, ts, spots[0], rows)


async def load_india_vix(db: Database) -> float | None:
    async with db.session() as s:
        val = (await s.execute(_VIX_SQL)).scalar()
    return float(val) if val is not None else None
