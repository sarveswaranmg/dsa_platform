from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Host port 5433 maps to the compose Postgres (see infra/docker-compose.yml).
    database_url: str = "postgresql+asyncpg://dsa:dsa@localhost:5433/ai"
    env: str = "dev"

    # RS256 public key (PEM) used to verify tokens exam signs. AI never holds
    # a private key — it never issues tokens.
    rs256_public_key: str

    # S3 (localstack in dev). Presign endpoint is separate because URLs are
    # consumed outside the compose network (browser/host), where the
    # in-network hostname `localstack` does not resolve.
    s3_endpoint_url: str = "http://localhost:4566"
    s3_presign_endpoint_url: str = "http://localhost:4566"
    s3_bucket: str = "ai-artifacts"
    # Origins allowed to PUT resume files straight to S3 (dev bootstrap).
    s3_cors_origins: list[str] = ["http://localhost:5173"]
    s3_presign_ttl_seconds: int = 900
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_region: str = "us-east-1"

    # LLMClient backend (app/llm/client.py). Defaults to a deterministic mock
    # so dev/CI never need a real API key or make a real network call.
    llm_backend: str = "mock"  # mock | anthropic
    anthropic_api_key: str = ""

    # GitHubClient backend (app/clients/github.py). Public repo/language data
    # needs no token; "mock" still avoids live network calls in tests/CI.
    github_backend: str = "mock"  # mock | real

    # judge-gen SQS lane (Phase 2 Slice 2) — differential testing during
    # question generation. Independent of exam's judge-live queues.
    sqs_endpoint_url: str = "http://localhost:4566"
    gen_jobs_queue: str = "dsa-judge-gen"
    gen_results_queue: str = "dsa-judge-gen-results"
    # Started in the app lifespan; tests leave it off and drive the
    # message-handling function directly (same pattern as exam's
    # enable_verdict_consumer).
    enable_gen_result_consumer: bool = True

    # Question service (HTTP only — no code imports). Used by the generation
    # results consumer to create a question once solutions agree; the
    # internal endpoint needs no bearer token (see app/clients/question_service.py).
    question_service_url: str = "http://localhost:8002"

    # Real inputs (100) would make the test suite extremely slow — tests
    # override this to something small.
    generation_input_count: int = 100
    # Max solution/validation attempts before a generation job is marked
    # failed (the problem draft itself is only ever generated once).
    generation_max_attempts: int = 3
    generation_agreement_threshold: float = 0.95

    # Test-case factory (Phase 2 Slice 3) — candidate counts per case type
    # for the default (async) variant.
    testcase_factory_edge_count: int = 10
    testcase_factory_adversarial_count: int = 10
    testcase_factory_stress_count: int = 10
    # On-demand (synchronous) variant, for mid-exam follow-ups: fewer
    # cases, split evenly-ish across the three types, hard-capped by a
    # wall-clock deadline. Tests override both to keep the timeout test fast.
    testcase_factory_sync_case_count: int = 10
    testcase_factory_sync_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from env vars


def validate_production_config(settings: Settings) -> None:
    if settings.env != "production":
        return
    if settings.llm_backend == "anthropic" and not settings.anthropic_api_key:
        raise RuntimeError(
            "ENV=production is set with LLM_BACKEND=anthropic but "
            "ANTHROPIC_API_KEY is missing"
        )
