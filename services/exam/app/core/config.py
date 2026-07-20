from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Host port 5433 maps to the compose Postgres (see infra/docker-compose.yml).
    database_url: str = "postgresql+asyncpg://dsa:dsa@localhost:5433/exam"
    redis_url: str = "redis://localhost:6379/0"
    env: str = "dev"

    jwt_secret: str = "dev-jwt-secret-change-me-not-for-production-use"
    access_token_ttl_seconds: int = 900  # 15 minutes
    refresh_token_ttl_seconds: int = 604_800  # 7 days


@lru_cache
def get_settings() -> Settings:
    return Settings()
