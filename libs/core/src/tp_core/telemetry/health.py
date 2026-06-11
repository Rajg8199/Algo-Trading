"""Health/readiness/metrics endpoint for daemon services.

Every service (recorder, scheduler, telegram) runs this tiny Starlette app
alongside its main loop:

    /health  -> 200 while the process event loop is alive (liveness)
    /ready   -> 200 only when dependencies are up and the service is doing
                its job (readiness; drives Prometheus `up`-style alerting)
    /metrics -> Prometheus exposition

FastAPI services mount the same routes natively instead.
"""

import asyncio
from dataclasses import dataclass, field

import uvicorn
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


@dataclass
class HealthState:
    """Mutable readiness state owned by the service's main loop."""

    service: str
    _components: dict[str, bool] = field(default_factory=dict)

    def set_ready(self, component: str, ready: bool) -> None:
        self._components[component] = ready

    @property
    def ready(self) -> bool:
        return bool(self._components) and all(self._components.values())

    @property
    def detail(self) -> dict[str, bool]:
        return dict(self._components)


def build_health_app(state: HealthState) -> Starlette:
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"service": state.service, "status": "alive"})

    async def ready(_: Request) -> JSONResponse:
        code = 200 if state.ready else 503
        return JSONResponse(
            {"service": state.service, "ready": state.ready, "components": state.detail},
            status_code=code,
        )

    async def metrics(_: Request) -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/ready", ready),
            Route("/metrics", metrics),
        ]
    )


async def serve_health(state: HealthState, port: int) -> None:
    """Run the health server forever; callers schedule this as a task."""
    config = uvicorn.Config(
        build_health_app(state),
        host="0.0.0.0",  # noqa: S104 — bound inside the docker network only
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_with_health(
    main: asyncio.Future[None] | asyncio.Task[None], state: HealthState, port: int
) -> None:
    """Run a service main task and the health server; first failure cancels both."""
    health_task = asyncio.create_task(serve_health(state, port), name="health-server")
    done, pending = await asyncio.wait({main, health_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        if exc is not None:
            raise exc
