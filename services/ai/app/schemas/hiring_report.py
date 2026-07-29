from typing import Literal

from pydantic import BaseModel, Field


class HiringReportEvidence(BaseModel):
    question: str
    verdict: str | None
    approach: str | None
    complexity: str | None
    partial_score: float


class HiringReport(BaseModel):
    """Mirrors architecture.md §4.4.6 exactly. `evidence` is assembled
    deterministically by the consumer (session_evaluations + exam/question
    data) — the LLM only ever produces the narrative fields, via
    `LLMClient.synthesize_hiring_report`'s narrower `HiringReportNarrative`
    schema (see app/llm/client.py)."""

    seniority_match: str
    strong_areas: list[str]
    weak_areas: list[str]
    code_quality: str
    problem_solving: str
    overall_score: float = Field(ge=0.0, le=1.0)
    recommendation: Literal["proceed", "maybe", "reject"]
    evidence: list[HiringReportEvidence]
