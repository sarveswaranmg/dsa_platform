from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "gateway"

    # Upstreams (in-network; these services publish no host ports).
    exam_service_url: str = "http://localhost:8001"
    question_service_url: str = "http://localhost:8002"

    jwt_secret: str = "dev-jwt-secret-change-me-not-for-production-use"
    redis_url: str = "redis://localhost:6379/0"

    cors_origins: list[str] = ["http://localhost:5173"]

    # Fixed-window rate limits, per identity per window.
    rate_limit_window_seconds: int = 60
    rate_limit_default: int = 300
    # Public auth endpoints are the brute-force surface, so they get a much
    # tighter budget keyed on client IP.
    rate_limit_auth: int = 10

    upstream_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
