import logging
import time
from typing import Protocol

import httpx
from pydantic import BaseModel

from app.clients.github import GitHubSignals
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ExtractedProfile(BaseModel):
    years_exp: int
    domains: list[str]
    tech_stack: list[str]
    seniority_estimate: str
    weak_signals: list[str]
    strong_signals: list[str]


class LLMClient(Protocol):
    """Every LLM call in this service goes through this interface — never
    call a model API directly from a router or service layer."""

    async def extract_profile(
        self, resume_text: str, github_signals: GitHubSignals | None
    ) -> ExtractedProfile: ...


class MockLLMClient:
    """Default backend — deterministic, no network call, no API key
    required. Used everywhere in dev/CI unless LLM_BACKEND=anthropic is set
    explicitly with a real key."""

    async def extract_profile(
        self, resume_text: str, github_signals: GitHubSignals | None
    ) -> ExtractedProfile:
        return ExtractedProfile(
            years_exp=5,
            domains=["backend", "distributed systems"],
            tech_stack=(github_signals.top_languages if github_signals else ["Python"]),
            seniority_estimate="senior",
            weak_signals=[],
            strong_signals=["clear resume structure"],
        )


class AnthropicLLMClient:
    """Real Claude calls with structured output, bounded retries, and a
    per-call structured log line (model, tokens, latency, cost isn't known
    until the response — logged when available)."""

    _BASE_URL = "https://api.anthropic.com/v1/messages"
    _MODEL = "claude-sonnet-4-6"
    _MAX_ATTEMPTS = 3

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def extract_profile(
        self, resume_text: str, github_signals: GitHubSignals | None
    ) -> ExtractedProfile:
        prompt = (
            "Extract a structured candidate profile from this resume text. "
            "Respond with strict JSON matching the schema: years_exp (int), "
            "domains (string list), tech_stack (string list), "
            "seniority_estimate (string), weak_signals (string list), "
            "strong_signals (string list).\n\n"
            f"Resume:\n{resume_text}\n\n"
            f"GitHub signals: {github_signals}"
        )
        last_error: Exception | None = None
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        self._BASE_URL,
                        headers={
                            "x-api-key": self._api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": self._MODEL,
                            "max_tokens": 1024,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                usage = body.get("usage", {})
                logger.info(
                    "llm_call",
                    extra={
                        "extra_fields": {
                            "model": self._MODEL,
                            "attempt": attempt,
                            "input_tokens": usage.get("input_tokens"),
                            "output_tokens": usage.get("output_tokens"),
                            "latency_ms": int((time.monotonic() - started) * 1000),
                        }
                    },
                )
                text = body["content"][0]["text"]
                return ExtractedProfile.model_validate_json(text)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "llm_call_retry",
                    extra={"extra_fields": {"attempt": attempt, "error": str(exc)}},
                )
        assert last_error is not None
        raise last_error


def get_llm_client() -> LLMClient:
    # FastAPI dependency; overridden in tests to avoid live network calls.
    backend = get_settings().llm_backend
    if backend == "mock":
        return MockLLMClient()
    if backend == "anthropic":
        return AnthropicLLMClient(get_settings().anthropic_api_key)
    raise ValueError(f"Unknown LLM_BACKEND: {backend!r}")
