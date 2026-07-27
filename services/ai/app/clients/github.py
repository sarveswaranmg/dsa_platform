from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class GitHubSignals:
    top_languages: list[str]
    public_repo_count: int
    total_stars: int


class GitHubClient(Protocol):
    """One provider interface; real/mock impls slot in behind it."""

    async def fetch_signals(self, handle: str) -> GitHubSignals: ...


class MockGitHubClient:
    """Dev/test default — deterministic fixture signals, no network call."""

    async def fetch_signals(self, handle: str) -> GitHubSignals:
        return GitHubSignals(
            top_languages=["Python", "TypeScript"],
            public_repo_count=12,
            total_stars=34,
        )


class RealGitHubClient:
    """Public GitHub REST API — no token needed for public repo/language
    data, so there's no secret to manage. Still not exercised in tests
    (mocked via dependency override) to keep the suite hermetic."""

    _BASE_URL = "https://api.github.com"

    async def fetch_signals(self, handle: str) -> GitHubSignals:
        async with httpx.AsyncClient(base_url=self._BASE_URL, timeout=10.0) as client:
            response = await client.get(f"/users/{handle}/repos", params={"per_page": 100})
            response.raise_for_status()
            repos = response.json()

        languages: dict[str, int] = {}
        total_stars = 0
        for repo in repos:
            if repo.get("language"):
                languages[repo["language"]] = languages.get(repo["language"], 0) + 1
            total_stars += repo.get("stargazers_count", 0)

        top_languages = [
            lang for lang, _ in sorted(languages.items(), key=lambda kv: kv[1], reverse=True)
        ][:5]
        return GitHubSignals(
            top_languages=top_languages,
            public_repo_count=len(repos),
            total_stars=total_stars,
        )


def get_github_client() -> GitHubClient:
    # FastAPI dependency; overridden in tests to avoid live network calls.
    backend = get_settings().github_backend
    if backend == "mock":
        return MockGitHubClient()
    if backend == "real":
        return RealGitHubClient()
    raise ValueError(f"Unknown GITHUB_BACKEND: {backend!r}")
