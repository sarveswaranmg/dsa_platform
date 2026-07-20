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

    # Question service (HTTP only — no code imports). Host default reaches the
    # compose-mapped port; inside the compose network it is http://question:8000.
    question_service_url: str = "http://localhost:8002"

    # Candidate invite flow.
    google_client_id: str = "dev-google-client-id.apps.googleusercontent.com"
    google_client_secret: str = "dev-google-client-secret"
    frontend_base_url: str = "http://localhost:5173"
    email_backend: str = "console"  # console | (ses later)


@lru_cache
def get_settings() -> Settings:
    return Settings()
