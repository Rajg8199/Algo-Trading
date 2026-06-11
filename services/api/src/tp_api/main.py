"""FastAPI application factory and entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from tp_api.deps import build_state
from tp_api.routers import auth, system, trading
from tp_core.config import get_settings
from tp_core.telemetry import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    state = build_state()
    app.state.container = state
    try:
        yield
    finally:
        await state.bus.close()
        await state.db.close()


def create_app() -> FastAPI:
    configure_logging("api", get_settings().log_level)
    app = FastAPI(title="trading-platform", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(trading.router)
    return app


app = create_app()


def cli() -> None:
    uvicorn.run(
        "tp_api.main:app",
        host="0.0.0.0",  # noqa: S104 — bound inside the docker network only
        port=get_settings().api_port,
        log_level="warning",
    )


if __name__ == "__main__":
    cli()
