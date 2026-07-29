from datetime import datetime

from pydantic import BaseModel


class HiringReportEvidence(BaseModel):
    question: str
    verdict: str | None
    approach: str | None
    complexity: str | None
    partial_score: float


class HiringReportResponse(BaseModel):
    """Mirrors architecture.md §4.4.6's HiringReport shape exactly. Assembled
    by ai (services/ai/app/schemas/hiring_report.py) and pushed here via
    POST /internal/sessions/{id}/report — this is a served-read cache, not
    where the report is authored."""

    seniority_match: str
    strong_areas: list[str]
    weak_areas: list[str]
    code_quality: str
    problem_solving: str
    overall_score: float
    recommendation: str
    evidence: list[HiringReportEvidence]
    generated_at: datetime
