"""Upstox OAuth callback: completes the daily semi-manual re-auth flow."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from tp_api.deps import AppState, get_state
from tp_core.models import Severity
from tp_core.redis import AlertEvent, AlertQueue
from tp_core.telemetry.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth")

State = Annotated[AppState, Depends(get_state)]


@router.get("/upstox/callback", response_class=PlainTextResponse)
async def upstox_callback(state: State, code: str | None = None) -> str:
    if not code:
        raise HTTPException(status_code=400, detail="missing authorization code")
    try:
        await state.auth.exchange_code(code)
    except Exception as exc:
        log.exception("token_exchange_failed")
        raise HTTPException(status_code=502, detail="token exchange failed") from exc
    await AlertQueue(state.bus).push(
        AlertEvent(
            severity=Severity.INFO,
            source="api",
            dedup_key="token_refreshed",
            message="✅ Upstox token refreshed — feed authorized for today.",
        )
    )
    log.info("token_refreshed")
    return "Token refreshed. You can close this tab."
