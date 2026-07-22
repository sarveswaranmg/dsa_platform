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

    # Candidate invite flow.
    google_client_id: str = "dev-google-client-id.apps.googleusercontent.com"
    google_client_secret: str = "dev-google-client-secret"
    frontend_base_url: str = "http://localhost:5173"
    email_backend: str = "console"  # console | (ses later)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from env vars
