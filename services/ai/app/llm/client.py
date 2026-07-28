import logging
import time
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, TypeAdapter

from app.clients.github import GitHubSignals
from app.core.config import get_settings
from app.generation.schemas import (
    DIFFICULTY_BANDS,
    AvailableTopic,
    BlueprintSlot,
    BlueprintSpec,
    GeneratedExample,
    GeneratedQuestionDraft,
    GeneratedTestCase,
    InputVar,
)
from app.models.candidate_profile import CandidateProfile

logger = logging.getLogger(__name__)

SolutionRole = Literal["reference", "brute_force"]


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

    async def draft_question(
        self, topic: str, difficulty_band: str, language_targets: list[str]
    ) -> GeneratedQuestionDraft: ...

    async def generate_solution(self, draft: GeneratedQuestionDraft, role: SolutionRole) -> str: ...

    async def generate_test_cases(
        self,
        draft: GeneratedQuestionDraft,
        *,
        edge_count: int,
        adversarial_count: int,
        stress_count: int,
    ) -> list[GeneratedTestCase]: ...

    async def propose_blueprint(
        self,
        profile: CandidateProfile,
        *,
        target_role: str,
        seniority_band: str,
        available_topics: list[AvailableTopic],
    ) -> BlueprintSpec: ...


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

    async def draft_question(
        self, topic: str, difficulty_band: str, language_targets: list[str]
    ) -> GeneratedQuestionDraft:
        lo, _hi = DIFFICULTY_BANDS[difficulty_band]
        return GeneratedQuestionDraft(
            title="Add Two Numbers",
            statement_md=(
                f"Read two integers `a` and `b` (one per line); print `a + b`. Topic: {topic}."
            ),
            constraints_md="1 <= a, b <= 1000",
            examples=[GeneratedExample(input="2\n3", output="5")],
            starter_code={lang: "# read a and b\n" for lang in language_targets},
            input_spec=[
                InputVar(name="a", kind="int", min_value=1, max_value=1000),
                InputVar(name="b", kind="int", min_value=1, max_value=1000),
            ],
            difficulty=lo,
        )

    async def generate_solution(self, draft: GeneratedQuestionDraft, role: SolutionRole) -> str:
        # Both roles return the same trivially-correct program — a fast,
        # deterministic fixture that always agrees with itself in tests.
        return "a = int(input())\nb = int(input())\nprint(a + b)\n"

    async def generate_test_cases(
        self,
        draft: GeneratedQuestionDraft,
        *,
        edge_count: int,
        adversarial_count: int,
        stress_count: int,
    ) -> list[GeneratedTestCase]:
        # Cycles through a few fixed, in-bounds (a, b) pairs — valid against
        # the mock draft's input_spec regardless of requested counts, so
        # tests exercise the full pipeline without a real LLM call.
        pairs = [(1, 1), (1000, 1000), (500, 500), (1, 1000), (1000, 1)]
        cases: list[GeneratedTestCase] = []
        counts: list[tuple[Literal["edge", "adversarial", "stress"], int]] = [
            ("edge", edge_count),
            ("adversarial", adversarial_count),
            ("stress", stress_count),
        ]
        for case_type, count in counts:
            for i in range(count):
                a, b = pairs[i % len(pairs)]
                cases.append(
                    GeneratedTestCase(
                        input=f"{a}\n{b}",
                        description=f"mock {case_type} case {i + 1}",
                        case_type=case_type,
                    )
                )
        return cases

    async def propose_blueprint(
        self,
        profile: CandidateProfile,
        *,
        target_role: str,
        seniority_band: str,
        available_topics: list[AvailableTopic],
    ) -> BlueprintSpec:
        # Small fixed spec over whatever topics were actually passed in, so
        # the whole flow is testable with no real key — same philosophy as
        # every other mock in this service. Weights are split evenly across
        # up to 2 topics, with any remainder folded into the last slot so
        # they always sum to exactly 100 (exam's blueprint schema requires
        # this, and requires unique topic_ids — picking distinct topics
        # from `available_topics` satisfies that for free).
        chosen = available_topics[:2]
        band: Literal["easy", "medium", "hard"] = "medium"
        lo, hi = DIFFICULTY_BANDS[band]
        base_weight = 100 // len(chosen)
        last_weight = 100 - base_weight * (len(chosen) - 1)
        slots = []
        for index, topic in enumerate(chosen):
            weight = base_weight if index < len(chosen) - 1 else last_weight
            slots.append(
                BlueprintSlot(
                    topic_id=topic.id,
                    weight=weight,
                    difficulty_band=band,
                    difficulty_min=lo,
                    difficulty_max=hi,
                    question_count=2,
                )
            )
        return BlueprintSpec(
            topic_mix=slots,
            total_duration_minutes=90,
            rationale=(
                f"Mock proposal for a {seniority_band} {target_role} candidate "
                f"(years_exp={profile.years_exp})."
            ),
        )


class AnthropicLLMClient:
    """Real Claude calls with structured output, bounded retries, and a
    per-call structured log line (model, tokens, latency, cost isn't known
    until the response — logged when available)."""

    _BASE_URL = "https://api.anthropic.com/v1/messages"
    _DRAFT_MODEL = "claude-sonnet-4-6"
    _REFERENCE_MODEL = "claude-haiku-4-5"
    _BRUTE_FORCE_MODEL = "claude-haiku-4-5"
    _MAX_ATTEMPTS = 3

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def _call(self, prompt: str, *, model: str, temperature: float = 1.0) -> str:
        """One structured-output call with bounded retries. Returns the raw
        response text (callers parse/validate it into their own schema)."""
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
                            "model": model,
                            "max_tokens": 2048,
                            "temperature": temperature,
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
                            "model": model,
                            "attempt": attempt,
                            "input_tokens": usage.get("input_tokens"),
                            "output_tokens": usage.get("output_tokens"),
                            "latency_ms": int((time.monotonic() - started) * 1000),
                        }
                    },
                )
                text: str = body["content"][0]["text"]
                return text
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "llm_call_retry",
                    extra={"extra_fields": {"attempt": attempt, "error": str(exc)}},
                )
        assert last_error is not None
        raise last_error

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
        text = await self._call(prompt, model=self._DRAFT_MODEL)
        return ExtractedProfile.model_validate_json(text)

    async def draft_question(
        self, topic: str, difficulty_band: str, language_targets: list[str]
    ) -> GeneratedQuestionDraft:
        prompt = (
            f"Draft a DSA interview question for topic {topic!r}, difficulty "
            f"band {difficulty_band!r}. Respond with strict JSON matching: "
            "title, statement_md, constraints_md, examples (list of "
            "{input, output}), starter_code (map of language to code for "
            f"languages {language_targets}), input_spec (list of "
            "{name, kind: int|int_array|string, min_value, max_value, "
            "length_min, length_max, charset}) describing each input "
            "variable in the order it appears on stdin, and difficulty "
            "(int 1-5). input_spec must be precise enough that a program "
            "can generate valid random test inputs from it without further "
            "guidance."
        )
        text = await self._call(prompt, model=self._DRAFT_MODEL)
        return GeneratedQuestionDraft.model_validate_json(text)

    async def generate_solution(self, draft: GeneratedQuestionDraft, role: SolutionRole) -> str:
        if role == "reference":
            model, temperature = self._REFERENCE_MODEL, 0.3
            style = "the optimal approach, with a brief complexity comment"
        else:
            model, temperature = self._BRUTE_FORCE_MODEL, 0.9
            style = (
                "a straightforward brute-force approach, written independently "
                "from any optimal solution — do not optimize"
            )
        prompt = (
            f"Problem:\n{draft.statement_md}\n\nConstraints:\n{draft.constraints_md}\n\n"
            f"Input format (one value per line, in order): "
            f"{[v.name for v in draft.input_spec]}\n\n"
            f"Write a complete Python 3 solution reading from stdin and "
            f"printing to stdout, using {style}. Respond with only the code, "
            "no markdown fences, no explanation."
        )
        return await self._call(prompt, model=model, temperature=temperature)

    async def generate_test_cases(
        self,
        draft: GeneratedQuestionDraft,
        *,
        edge_count: int,
        adversarial_count: int,
        stress_count: int,
    ) -> list[GeneratedTestCase]:
        prompt = (
            f"Problem:\n{draft.statement_md}\n\nConstraints:\n{draft.constraints_md}\n\n"
            f"Input format (one value per line, in order): "
            f"{[v.name for v in draft.input_spec]}\n\n"
            f"Generate exactly {edge_count} edge cases, {adversarial_count} "
            f"adversarial cases, and {stress_count} stress cases (values "
            "near the constraint boundaries) — each within the declared "
            "constraints. Respond with a strict JSON list, each element "
            '{"input": "...", "description": "...", "case_type": '
            '"edge"|"adversarial"|"stress"}. `input` must have exactly '
            f"{len(draft.input_spec)} lines, one per input variable in "
            "order, no markdown fences, no explanation."
        )
        text = await self._call(prompt, model=self._DRAFT_MODEL)
        return TypeAdapter(list[GeneratedTestCase]).validate_json(text)

    async def propose_blueprint(
        self,
        profile: CandidateProfile,
        *,
        target_role: str,
        seniority_band: str,
        available_topics: list[AvailableTopic],
    ) -> BlueprintSpec:
        topics_desc = ", ".join(f"{t.id} ({t.name})" for t in available_topics)
        prompt = (
            f"Propose an exam blueprint for a {seniority_band} {target_role} "
            f"candidate. Candidate signals: years_exp={profile.years_exp}, "
            f"domains={profile.domains}, tech_stack={profile.tech_stack}, "
            f"seniority_estimate={profile.seniority_estimate}, "
            f"strong_signals={profile.strong_signals}, "
            f"weak_signals={profile.weak_signals}.\n\n"
            f"Available topics (id, name): {topics_desc}\n\n"
            "Respond with strict JSON matching: topic_mix (list of "
            "{topic_id: one of the available topic ids above, weight: int, "
            "difficulty_band: \"easy\"|\"medium\"|\"hard\", difficulty_min: int "
            "1-5, difficulty_max: int 1-5, question_count: int}), "
            "total_duration_minutes (int), rationale (string). "
            "topic_mix weights must sum to exactly 100 and must not repeat a "
            "topic_id. difficulty_min/difficulty_max must match the band: "
            "easy=1-2, medium=2-3, hard=4-5."
        )
        text = await self._call(prompt, model=self._DRAFT_MODEL)
        return BlueprintSpec.model_validate_json(text)


def get_llm_client() -> LLMClient:
    # FastAPI dependency; overridden in tests to avoid live network calls.
    backend = get_settings().llm_backend
    if backend == "mock":
        return MockLLMClient()
    if backend == "anthropic":
        return AnthropicLLMClient(get_settings().anthropic_api_key)
    raise ValueError(f"Unknown LLM_BACKEND: {backend!r}")
