from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Host port 5433 maps to the compose Postgres (see infra/docker-compose.yml).
    database_url: str = "postgresql+asyncpg://dsa:dsa@localhost:5433/question"
    env: str = "dev"

    # RS256 public key (PEM) used to verify tokens exam signs. Question never
    # holds a private key — it never issues tokens.
    rs256_public_key: str

    # S3 (localstack in dev). Presign endpoint is separate because URLs are
    # consumed outside the compose network (browser/host), where the
    # in-network hostname `localstack` does not resolve.
    s3_endpoint_url: str = "http://localhost:4566"
    s3_presign_endpoint_url: str = "http://localhost:4566"
    s3_bucket: str = "question-artifacts"
    # Origins allowed to PUT test-case files straight to S3 (dev bootstrap).
    s3_cors_origins: list[str] = ["http://localhost:5173"]
    s3_presign_ttl_seconds: int = 900
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_region: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from env vars
