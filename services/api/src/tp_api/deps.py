"""Application state and dependency injection for routers."""

from dataclasses import dataclass

from fastapi import Request

from tp_core.config import Settings, get_settings
from tp_core.db import Database
from tp_core.db.repos import TokenRepo
from tp_core.redis import RedisBus
from tp_upstox.auth import UpstoxAuth


@dataclass
class AppState:
    settings: Settings
    db: Database
    bus: RedisBus
    auth: UpstoxAuth


def build_state() -> AppState:
    settings = get_settings()
    db = Database(settings)
    return AppState(
        settings=settings,
        db=db,
        bus=RedisBus(settings),
        auth=UpstoxAuth(settings, TokenRepo(db)),
    )


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.container
    return state
