"""Central configuration. Every service constructs exactly one Settings instance.

All values come from the environment (.env in dev, injected env in containers).
No service reads os.environ directly anywhere else in the codebase.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"

    # Postgres / TimescaleDB
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "trading"
    postgres_user: str = "trading"
    postgres_password: SecretStr = SecretStr("trading")
    db_pool_min: int = 2
    db_pool_max: int = 10

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Upstox
    upstox_api_key: str = ""
    upstox_api_secret: SecretStr = SecretStr("")
    upstox_redirect_uri: str = ""
    upstox_rest_rate_limit_per_sec: int = 20
    upstox_ws_max_instruments: int = 400

    # Telegram
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_allowed_chat_id: int = 0

    @field_validator("telegram_allowed_chat_id", mode="before")
    @classmethod
    def _empty_chat_id_is_zero(cls, value: object) -> object:
        return 0 if value == "" else value

    # Recorder
    recorder_chain_poll_seconds: int = 60
    recorder_batch_max_rows: int = 500
    recorder_batch_flush_seconds: float = 1.0
    recorder_atm_strike_window: int = Field(default=15, ge=1, le=50)

    # Health/metrics ports (each daemon serves /health /ready /metrics)
    api_port: int = 8000
    recorder_health_port: int = 8001
    scheduler_health_port: int = 8002
    telegram_health_port: int = 8003

    # Data lake
    datalake_root: str = "./datalake"

    # ClickHouse (optional analytics profile)
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 9000
    clickhouse_db: str = "analytics"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
