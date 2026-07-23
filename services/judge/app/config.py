from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQS (localstack in dev).
    sqs_endpoint_url: str = "http://localhost:4566"
    submissions_queue: str = "dsa-submissions"
    verdicts_queue: str = "dsa-verdicts"

    # S3 (localstack in dev) — where the question service stored test cases.
    s3_endpoint_url: str = "http://localhost:4566"
    s3_bucket: str = "question-artifacts"

    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_region: str = "us-east-1"

    # Runner images (built from runners/<lang>/Dockerfile).
    image_python: str = "dsa-judge-python:3.12"
    image_java: str = "dsa-judge-java:21"
    image_cpp: str = "dsa-judge-cpp:13"

    # Docker runtime for sandboxed containers: "runc" (default) or "gvisor"
    # (maps to --runtime=runsc). See docs/DECISIONS.md.
    judge_runtime: str = "runc"

    # Scratch root on the judge host for per-submission artifact dirs.
    scratch_root: str = "/tmp/dsa-judge"

    # Grace added to a case's wall limit before the worker force-kills the
    # container (covers process startup, not the measured runtime).
    wall_grace_seconds: float = 2.0

    # Hard cap on captured stdout bytes (paired with the fsize ulimit).
    max_output_bytes: int = 1_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
