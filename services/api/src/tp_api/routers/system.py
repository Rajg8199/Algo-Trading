"""Health/readiness/metrics + system status endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from sqlalchemy import text

from tp_api.deps import AppState, get_state

router = APIRouter()

State = Annotated[AppState, Depends(get_state)]

STATUS_SQL = text("""
    SELECT
      (SELECT max(ts) FROM ticks)        AS last_tick,
      (SELECT max(ts) FROM option_chain) AS last_chain,
      (SELECT count(*) FROM ticks        WHERE ts > now() - interval '5 minutes') AS ticks_5m,
      (SELECT count(*) FROM option_chain WHERE ts > now() - interval '5 minutes') AS chain_5m,
      (SELECT count(*) FROM data_gaps WHERE NOT resolved) AS open_gaps
""")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"service": "api", "status": "alive"}


@router.get("/ready")
async def ready(state: State) -> dict[str, Any]:
    checks = {"db": await state.db.ping(), "redis": await state.bus.ping()}
    return {"ready": all(checks.values()), "components": checks}


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/v1/status")
async def status(state: State) -> dict[str, Any]:
    async with state.db.session() as s:
        row = (await s.execute(STATUS_SQL)).one()
    token = await state.auth.current_token()
    return {
        "last_tick": row.last_tick.isoformat() if row.last_tick else None,
        "last_chain_snapshot": row.last_chain.isoformat() if row.last_chain else None,
        "ticks_last_5m": row.ticks_5m,
        "chain_rows_last_5m": row.chain_5m,
        "open_data_gaps": row.open_gaps,
        "upstox_token": "valid" if token else "missing/expired",
    }
