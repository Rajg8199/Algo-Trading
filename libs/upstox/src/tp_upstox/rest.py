"""Upstox REST client: option chain, instrument master, quotes.

All calls go through a token-bucket rate limiter set well below published
plan limits; the budget is configuration, not code.
"""

import asyncio
import gzip
import json
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from tp_core.config import Settings
from tp_core.models import ChainRow, Exchange, Instrument, OptionType, Segment
from tp_core.telemetry.logging import get_logger
from tp_core.telemetry.metrics import UPSTOX_REST_LATENCY
from tp_core.timeutils import now_utc

log = get_logger(__name__)

API_BASE = "https://api.upstox.com/v2"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"

INDEX_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "SENSEX": "BSE_INDEX|SENSEX",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "INDIAVIX": "NSE_INDEX|India VIX",
}
_INDEX_KEY_TO_UNDERLYING = {v: k for k, v in INDEX_KEYS.items()}


class RateLimiter:
    """Simple token bucket: `rate` requests per second, burst of `rate`."""

    def __init__(self, rate: int) -> None:
        self._rate = rate
        self._tokens = float(rate)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self._rate, self._tokens + (now - self._last) * self._rate)
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._rate)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class UpstoxRest:
    def __init__(self, settings: Settings, token_provider: Any) -> None:
        """token_provider: object with async current_token() -> str | None."""
        self._settings = settings
        self._auth = token_provider
        self._limiter = RateLimiter(settings.upstox_rest_rate_limit_per_sec)
        self._client = httpx.AsyncClient(base_url=API_BASE, timeout=20)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        token = await self._auth.current_token()
        if token is None:
            raise RuntimeError("no valid Upstox access token")
        await self._limiter.acquire()
        endpoint = path.split("?")[0]
        start = time.monotonic()
        response = await self._client.get(
            path,
            params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        UPSTOX_REST_LATENCY.labels(endpoint=endpoint).observe(time.monotonic() - start)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload

    async def option_chain(
        self,
        underlying: str,
        expiry: date,
        key_to_id: dict[str, int],
    ) -> list[ChainRow]:
        """Full option chain for one underlying+expiry, mapped to ChainRows.

        key_to_id maps upstox instrument keys -> our instrument_id; rows whose
        key is unknown are dropped and logged (instrument master refresh will
        pick them up next morning).
        """
        payload = await self._get(
            "/option/chain",
            params={
                "instrument_key": INDEX_KEYS[underlying],
                "expiry_date": expiry.isoformat(),
            },
        )
        snapshot_ts = now_utc()
        rows: list[ChainRow] = []
        unknown = 0
        for entry in payload.get("data", []):
            spot = _decimal(entry.get("underlying_spot_price"))
            for leg_field, _opt_type in (("call_options", "CE"), ("put_options", "PE")):
                leg = entry.get(leg_field)
                if not leg:
                    continue
                instrument_key = leg.get("instrument_key", "")
                instrument_id = key_to_id.get(instrument_key)
                if instrument_id is None:
                    unknown += 1
                    continue
                md = leg.get("market_data", {})
                greeks = leg.get("option_greeks", {})
                rows.append(
                    ChainRow(
                        ts=snapshot_ts,
                        instrument_id=instrument_id,
                        ltp=_decimal(md.get("ltp")),
                        bid=_decimal(md.get("bid_price")),
                        ask=_decimal(md.get("ask_price")),
                        bid_qty=md.get("bid_qty"),
                        ask_qty=md.get("ask_qty"),
                        volume=md.get("volume"),
                        oi=md.get("oi"),
                        oi_prev_day=md.get("prev_oi"),
                        iv=greeks.get("iv"),
                        delta=greeks.get("delta"),
                        gamma=greeks.get("gamma"),
                        theta=greeks.get("theta"),
                        vega=greeks.get("vega"),
                        spot=spot,
                    )
                )
        if unknown:
            log.warning("chain_rows_unknown_instruments", underlying=underlying, count=unknown)
        return rows

    async def ltp(self, instrument_keys: list[str]) -> dict[str, float]:
        payload = await self._get(
            "/market-quote/ltp", params={"instrument_key": ",".join(instrument_keys)}
        )
        return {
            entry.get("instrument_token", key): entry["last_price"]
            for key, entry in payload.get("data", {}).items()
        }


async def download_instrument_master(
    underlyings: frozenset[str] = frozenset({"NIFTY", "SENSEX", "BANKNIFTY"}),
) -> list[Instrument]:
    """Download and parse the Upstox instrument master for our universe: index
    spots, index futures, and index options on NIFTY/SENSEX/BANKNIFTY + India VIX."""
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(INSTRUMENTS_URL)
        response.raise_for_status()
    raw = json.loads(gzip.decompress(response.content))

    instruments: list[Instrument] = []
    for item in raw:
        segment_code = item.get("segment", "")
        name = (item.get("asset_symbol") or item.get("name") or "").upper().replace(" ", "")
        instrument_type = item.get("instrument_type", "")

        if segment_code in ("NSE_INDEX", "BSE_INDEX"):
            # Match on the stable instrument_key, not trading_symbol — Upstox has
            # changed the latter (e.g. "NIFTY 50" -> "NIFTY", Bank Nifty ->
            # "BANKNIFTY"), which silently dropped indices from the universe.
            mapped = _INDEX_KEY_TO_UNDERLYING.get(item.get("instrument_key", ""))
            if mapped is None:
                continue
            instruments.append(
                Instrument(
                    upstox_key=item["instrument_key"],
                    exchange=Exchange.NSE if segment_code.startswith("NSE") else Exchange.BSE,
                    segment=Segment.INDEX,
                    underlying=mapped,
                )
            )
            continue

        if segment_code not in ("NSE_FO", "BSE_FO") or name not in underlyings:
            continue
        exchange = Exchange.NSE if segment_code == "NSE_FO" else Exchange.BSE
        expiry_ms = item.get("expiry")
        expiry = (
            datetime.fromtimestamp(expiry_ms / 1000, tz=now_utc().tzinfo).date()
            if expiry_ms
            else None
        )
        if instrument_type == "FUT":
            instruments.append(
                Instrument(
                    upstox_key=item["instrument_key"],
                    exchange=exchange,
                    segment=Segment.FUT,
                    underlying=name,
                    expiry=expiry,
                    lot_size=item.get("lot_size", 1),
                    tick_size=_decimal(item.get("tick_size")),
                )
            )
        elif instrument_type in ("CE", "PE"):
            instruments.append(
                Instrument(
                    upstox_key=item["instrument_key"],
                    exchange=exchange,
                    segment=Segment.OPT,
                    underlying=name,
                    expiry=expiry,
                    strike=_decimal(item.get("strike_price")),
                    option_type=OptionType(instrument_type),
                    lot_size=item.get("lot_size", 1),
                    tick_size=_decimal(item.get("tick_size")),
                )
            )
    log.info("instrument_master_parsed", count=len(instruments))
    return instruments
