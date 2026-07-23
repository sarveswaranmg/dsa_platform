from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Host port 5433 maps to the compose Postgres (see infra/docker-compose.yml).
    database_url: str = "postgresql+asyncpg://dsa:dsa@localhost:5433/exam"
    redis_url: str = "redis://localhost:6379/0"
    env: str = "dev"

    # RS256 private key (PEM). Exam is the only service that signs — the
    # public key is derived from this in-memory, never configured separately.
    rs256_private_key: str
    access_token_ttl_seconds: int = 900  # 15 minutes
    refresh_token_ttl_seconds: int = 604_800  # 7 days

    # Question service (HTTP only — no code imports). Host default reaches the
    # compose-mapped port; inside the compose network it is http://question:8000.
    question_service_url: str = "http://localhost:8002"

    # Judge pipeline (SQS via localstack). The exam service publishes
    # submission jobs and consumes verdicts (no code imports — queue only).
    sqs_endpoint_url: str = "http://localhost:4566"
    submissions_queue: str = "dsa-submissions"
    verdicts_queue: str = "dsa-verdicts"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_region: str = "us-east-1"
    # Start the background verdict consumer in the app lifespan (dev/prod);
    # tests leave it off and call process_verdict_message directly.
    enable_verdict_consumer: bool = True

    # Candidate invite flow. Empty by default (not a fake-looking placeholder)
    # so validate_production_config can detect "not configured" cleanly.
    # google_client_id is the only one actually read by the current
    # client-side Google Identity Services flow (app/oidc/google.py) — the
    # other two aren't consumed by any code path today; they're validated in
    # production per CLAUDE.md's checklist and reserved for a future
    # server-side flow.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    frontend_base_url: str = "http://localhost:5173"
    email_backend: str = "console"  # console | ses
    ses_from_address: str = "no-reply@example.com"  # must be an SES-verified identity in prod


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from env vars


def validate_production_config(settings: Settings) -> None:
    if settings.env != "production":
        return
    missing = [
        name
        for name, value in (
            ("GOOGLE_CLIENT_ID", settings.google_client_id),
            ("GOOGLE_CLIENT_SECRET", settings.google_client_secret),
            ("GOOGLE_REDIRECT_URI", settings.google_redirect_uri),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"ENV=production is set but missing required config: {', '.join(missing)}"
        )
