import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.submission import CaseVerdictResponse


class SubmissionSummary(BaseModel):
    """One row in an exam's submission history (no source code)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_version_id: uuid.UUID
    session_id: uuid.UUID | None
    language: str
    mode: str
    status: str
    summary_verdict: str | None
    created_at: datetime


class SubmissionDetail(SubmissionSummary):
    """Full record for review, including the code the candidate submitted."""

    exam_id: uuid.UUID
    source: str
    compile_error: str | None
    cases: list[CaseVerdictResponse]
