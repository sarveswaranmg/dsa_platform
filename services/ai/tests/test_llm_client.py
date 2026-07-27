import pytest

from app.clients.github import GitHubSignals
from app.core.config import get_settings
from app.llm.client import AnthropicLLMClient, MockLLMClient, get_llm_client


async def test_mock_client_is_deterministic() -> None:
    client = MockLLMClient()
    first = await client.extract_profile("some resume text", None)
    second = await client.extract_profile("different text", None)
    assert first == second


async def test_mock_client_prefers_github_signals_for_tech_stack() -> None:
    client = MockLLMClient()
    signals = GitHubSignals(top_languages=["Rust"], public_repo_count=1, total_stars=0)
    profile = await client.extract_profile("resume", signals)
    assert profile.tech_stack == ["Rust"]


def test_get_llm_client_selects_mock_by_default() -> None:
    assert get_settings().llm_backend == "mock"
    assert isinstance(get_llm_client(), MockLLMClient)


def test_get_llm_client_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_backend", "bogus")
    with pytest.raises(ValueError, match="Unknown LLM_BACKEND"):
        get_llm_client()


def test_get_llm_client_selects_anthropic_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "llm_backend", "anthropic")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    assert isinstance(get_llm_client(), AnthropicLLMClient)
