from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Host port 5433 maps to the compose Postgres (see infra/docker-compose.yml).
    database_url: str = "postgresql+asyncpg://dsa:dsa@localhost:5433/question"
    env: str = "dev"

    jwt_secret: str = "dev-jwt-secret-change-me-not-for-production-use"

    # S3 (localstack in dev). Presign endpoint is separate because URLs are
    # consumed outside the compose network (browser/host), where the
    # in-network hostname `localstack` does not resolve.
    s3_endpoint_url: str = "http://localhost:4566"
    s3_presign_endpoint_url: str = "http://localhost:4566"
    s3_bucket: str = "question-artifacts"
    s3_presign_ttl_seconds: int = 900
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_region: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
