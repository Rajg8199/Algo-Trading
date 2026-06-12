"""Option-chain analytics queries: ATM IV, delta-bucket IVs, OI aggregates.

All functions read the option_chain hypertable via the shared Database and
return None when the data can't support the number — never interpolated
guesses. The close snapshot is taken at 15:25 IST (last clean snapshot
before closing auction noise).
"""

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import text

from tp_core.db import Database
from tp_core.timeutils import IST

CLOSE_SNAPSHOT_IST = time(15, 25)

# Latest snapshot at-or-before the close cut, per instrument, for one expiry.
_CHAIN_AT_CLOSE_SQL = text("""
    WITH cut AS (
        SELECT max(ts) AS snap_ts
        FROM option_chain oc
        JOIN instruments i USING (instrument_id)
        WHERE i.underlying = :underlying AND i.expiry = :expiry
          AND oc.ts BETWEEN :day_open AND :day_cut
    )
    SELECT i.strike, i.option_type, oc.iv, oc.delta, oc.oi, oc.spot, oc.ltp,
           oc.bid, oc.ask
    FROM option_chain oc
    JOIN instruments i USING (instrument_id)
    JOIN cut ON oc.ts = cut.snap_ts
    WHERE i.underlying = :underlying AND i.expiry = :expiry
""")


@dataclass(frozen=True)
class ChainClose:
    """One expiry's chain at the daily close cut."""

    underlying: str
    expiry: date
    spot: float
    rows: list["ChainRowLite"]


@dataclass
class ChainRowLite:
    strike: float
    option_type: str
    iv: float | None
    delta: float | None
    oi: float | None


async def load_chain_at_close(
    db: Database, underlying: str, expiry: date, trade_date: date
) -> ChainClose | None:
    day_open = datetime.combine(trade_date, time(9, 15), tzinfo=IST)
    day_cut = datetime.combine(trade_date, CLOSE_SNAPSHOT_IST, tzinfo=IST)
    async with db.session() as s:
        result = await s.execute(
            _CHAIN_AT_CLOSE_SQL,
            {
                "underlying": underlying,
                "expiry": expiry,
                "day_open": day_open,
                "day_cut": day_cut,
            },
        )
        records = result.mappings().all()
    if not records:
        return None
    spot_values = [float(r["spot"]) for r in records if r["spot"] is not None]
    if not spot_values:
        return None
    rows = [
        ChainRowLite(
            strike=float(r["strike"]),
            option_type=str(r["option_type"]),
            iv=float(r["iv"]) if r["iv"] is not None else None,
            delta=float(r["delta"]) if r["delta"] is not None else None,
            oi=float(r["oi"]) if r["oi"] is not None else None,
        )
        for r in records
    ]
    return ChainClose(underlying, expiry, spot_values[0], rows)


def atm_iv(chain: ChainClose) -> float | None:
    """ATM IV = mean of CE and PE IV at the strike nearest spot.
    Requires both legs with sane IVs; one-legged ATM is suspicious data."""
    by_strike: dict[float, dict[str, float]] = {}
    for row in chain.rows:
        if row.iv is None or not (1.0 < row.iv < 200.0):
            continue
        by_strike.setdefault(row.strike, {})[row.option_type] = row.iv
    candidates = [
        (abs(strike - chain.spot), legs)
        for strike, legs in by_strike.items()
        if "CE" in legs and "PE" in legs
    ]
    if not candidates:
        return None
    _, legs = min(candidates, key=lambda pair: pair[0])
    return (legs["CE"] + legs["PE"]) / 2


def iv_at_delta(chain: ChainClose, option_type: str, target_delta: float) -> float | None:
    """IV of the contract whose |delta| is closest to |target_delta|.
    Tolerance 0.10 — beyond that the strike grid doesn't support the bucket."""
    best: tuple[float, float] | None = None
    for row in chain.rows:
        if row.option_type != option_type or row.iv is None or row.delta is None:
            continue
        if not (1.0 < row.iv < 200.0):
            continue
        dist = abs(abs(row.delta) - abs(target_delta))
        if best is None or dist < best[0]:
            best = (dist, row.iv)
    if best is None or best[0] > 0.10:
        return None
    return best[1]


def total_oi(chain: ChainClose) -> float | None:
    values = [row.oi for row in chain.rows if row.oi is not None]
    return float(sum(values)) if values else None


def skew_metrics(chain: ChainClose) -> dict[str, float | None]:
    """25-delta skew measures, in vol points relative to ATM:
    put_skew_25d   = IV(25Δ put)  - IV(ATM)   (rich downside insurance)
    call_skew_25d  = IV(25Δ call) - IV(ATM)   (upside lottery demand)
    smile_curvature = (IV(25Δ put) + IV(25Δ call)) / 2 - IV(ATM)
    """
    iv_atm = atm_iv(chain)
    put25 = iv_at_delta(chain, "PE", 0.25)
    call25 = iv_at_delta(chain, "CE", 0.25)
    return {
        "put_skew_25d": (put25 - iv_atm) if (put25 is not None and iv_atm is not None) else None,
        "call_skew_25d": (call25 - iv_atm) if (call25 is not None and iv_atm is not None) else None,
        "smile_curvature": ((put25 + call25) / 2 - iv_atm)
        if (put25 is not None and call25 is not None and iv_atm is not None)
        else None,
    }
