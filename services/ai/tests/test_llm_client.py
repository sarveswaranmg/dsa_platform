import pytest

from app.clients.github import GitHubSignals
from app.core.config import get_settings
from app.generation.validate import validate_draft, validate_input
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


async def test_mock_client_drafts_a_valid_internally_consistent_question() -> None:
    client = MockLLMClient()
    draft = await client.draft_question("arrays", "easy", ["python"])
    assert validate_draft(draft, "easy", ["python"]) == []


async def test_mock_client_reference_and_brute_force_solutions_agree() -> None:
    client = MockLLMClient()
    draft = await client.draft_question("arrays", "easy", ["python"])
    reference = await client.generate_solution(draft, "reference")
    brute_force = await client.generate_solution(draft, "brute_force")
    assert reference == brute_force  # trivially-correct fixture, always agrees


async def test_mock_client_generates_valid_test_case_candidates() -> None:
    client = MockLLMClient()
    draft = await client.draft_question("arrays", "easy", ["python"])
    cases = await client.generate_test_cases(
        draft, edge_count=2, adversarial_count=3, stress_count=1
    )
    assert len(cases) == 6
    assert sum(1 for c in cases if c.case_type == "edge") == 2
    assert sum(1 for c in cases if c.case_type == "adversarial") == 3
    assert sum(1 for c in cases if c.case_type == "stress") == 1
    for case in cases:
        assert validate_input(case.input, draft.input_spec) == []


async def test_mock_client_evaluate_submission_ac_is_optimal_no_bug() -> None:
    client = MockLLMClient()
    assessment = await client.evaluate_submission(
        statement_md="stmt", constraints_md="1<=n<=10", language="python",
        source="print(1)", verdict="AC",
    )
    assert assessment.approach_correct is True
    assert assessment.is_optimal is True
    assert assessment.bug_severity == "none"
    assert assessment.bug_description is None


async def test_mock_client_evaluate_submission_non_ac_reports_a_minor_bug() -> None:
    client = MockLLMClient()
    assessment = await client.evaluate_submission(
        statement_md="stmt", constraints_md="1<=n<=10", language="python",
        source="print(1)", verdict="WA",
    )
    assert assessment.approach_correct is True
    assert assessment.is_optimal is False
    assert assessment.bug_severity == "minor"
    assert assessment.bug_description is not None


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
