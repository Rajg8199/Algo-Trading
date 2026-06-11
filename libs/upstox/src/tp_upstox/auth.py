"""Upstox OAuth token management.

Upstox access tokens expire daily (~03:30 IST). Fully headless refresh is not
supported by the provider, so the flow is semi-manual by design:

  1. Scheduler's token job calls `is_token_valid()` pre-market.
  2. If invalid, it pushes a P1 alert containing `login_url()` to Telegram.
  3. The user taps the link, authorizes; Upstox redirects to our FastAPI
     callback with ?code=...
  4. The callback calls `exchange_code()`, which stores the token in the DB.

Every other component reads the current token via `current_token()`.
"""

from datetime import UTC, datetime, time, timedelta
from urllib.parse import urlencode

import httpx

from tp_core.config import Settings
from tp_core.db.repos import TokenRepo
from tp_core.telemetry.metrics import TOKEN_VALID
from tp_core.timeutils import IST

PROVIDER = "upstox"
AUTH_BASE = "https://api.upstox.com/v2"


class UpstoxAuth:
    def __init__(self, settings: Settings, tokens: TokenRepo) -> None:
        self._settings = settings
        self._tokens = tokens

    def login_url(self) -> str:
        params = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.upstox_api_key,
                "redirect_uri": self._settings.upstox_redirect_uri,
            }
        )
        return f"{AUTH_BASE}/login/authorization/dialog?{params}"

    async def exchange_code(self, code: str) -> str:
        """Exchange an authorization code for an access token and persist it."""
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{AUTH_BASE}/login/authorization/token",
                data={
                    "code": code,
                    "client_id": self._settings.upstox_api_key,
                    "client_secret": self._settings.upstox_api_secret.get_secret_value(),
                    "redirect_uri": self._settings.upstox_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
        response.raise_for_status()
        access_token: str = response.json()["access_token"]
        await self._tokens.store(PROVIDER, access_token, self._next_expiry())
        TOKEN_VALID.set(1)
        return access_token

    async def current_token(self) -> str | None:
        row = await self._tokens.get(PROVIDER)
        if row is None:
            TOKEN_VALID.set(0)
            return None
        if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
            TOKEN_VALID.set(0)
            return None
        TOKEN_VALID.set(1)
        return row.access_token

    async def is_token_valid(self) -> bool:
        """Cheap remote validation: hit the profile endpoint with the stored token."""
        token = await self.current_token()
        if token is None:
            return False
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{AUTH_BASE}/user/profile",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        valid = response.status_code == 200
        TOKEN_VALID.set(1 if valid else 0)
        return valid

    @staticmethod
    def _next_expiry() -> datetime:
        """Tokens die at ~03:30 IST the next day; store a conservative 03:00 IST."""
        now_ist = datetime.now(IST)
        expiry_date = now_ist.date() + timedelta(days=1)
        return datetime.combine(expiry_date, time(3, 0), tzinfo=IST).astimezone(UTC)
