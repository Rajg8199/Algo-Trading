"""Builds the websocket hot set: indices + VIX + near futures + ATM±N strikes
for the active expiries of each underlying."""

from datetime import date
from decimal import Decimal

from tp_core.db.repos import InstrumentRepo
from tp_core.telemetry.logging import get_logger

log = get_logger(__name__)

STRIKE_STEP = {"NIFTY": Decimal(50), "SENSEX": Decimal(100)}


class SubscriptionSet:
    def __init__(
        self,
        keys: list[str],
        key_to_id: dict[str, int],
        id_to_underlying: dict[int, str],
    ) -> None:
        self.keys = keys
        self.key_to_id = key_to_id
        self.id_to_underlying = id_to_underlying


async def build_subscription_set(
    instruments: InstrumentRepo,
    spot_estimates: dict[str, Decimal],
    today: date,
    atm_window: int,
    max_instruments: int,
) -> SubscriptionSet:
    """Hot set = index spots + VIX + front/next options around ATM.

    spot_estimates: latest known spot per underlying (from DB or REST quote);
    used to center the strike window.
    """
    keys: list[str] = []
    key_to_id: dict[str, int] = {}
    id_to_underlying: dict[int, str] = {}

    index_rows = await instruments.by_upstox_keys(
        ["NSE_INDEX|Nifty 50", "BSE_INDEX|SENSEX", "NSE_INDEX|India VIX"]
    )
    index_underlying = {
        "NSE_INDEX|Nifty 50": "NIFTY",
        "BSE_INDEX|SENSEX": "SENSEX",
        "NSE_INDEX|India VIX": "INDIAVIX",
    }
    for key, iid in index_rows.items():
        keys.append(key)
        key_to_id[key] = iid
        id_to_underlying[iid] = index_underlying[key]

    for underlying in ("NIFTY", "SENSEX"):
        spot = spot_estimates.get(underlying)
        if spot is None:
            log.warning("no_spot_estimate_skipping_options", underlying=underlying)
            continue
        step = STRIKE_STEP[underlying]
        atm = (spot / step).quantize(Decimal(1)) * step
        lo, hi = atm - step * atm_window, atm + step * atm_window
        expiries = (await instruments.expiries(underlying, after=today))[:2]
        for expiry in expiries:
            for row in await instruments.active_options(underlying, expiry):
                if row.strike is None or not (lo <= row.strike <= hi):
                    continue
                keys.append(row.upstox_key)
                key_to_id[row.upstox_key] = row.instrument_id
                id_to_underlying[row.instrument_id] = underlying

    if len(keys) > max_instruments:
        log.warning("subscription_set_truncated", requested=len(keys), limit=max_instruments)
        keys = keys[:max_instruments]
        key_to_id = {k: key_to_id[k] for k in keys}
        id_to_underlying = {key_to_id[k]: id_to_underlying[key_to_id[k]] for k in keys}

    log.info("subscription_set_built", instruments=len(keys))
    return SubscriptionSet(keys, key_to_id, id_to_underlying)
