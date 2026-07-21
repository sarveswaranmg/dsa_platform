import uuid

from pydantic import BaseModel, ConfigDict, Field


class SubmitRequest(BaseModel):
    question_version_id: uuid.UUID
    language: str = Field(pattern="^(python|java|cpp)$")
    source: str = Field(min_length=1, max_length=200_000)


class CaseVerdictResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordinal: int
    verdict: str
    runtime_ms: int
    memory_kb: int


class SubmissionResponse(BaseModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    question_version_id: uuid.UUID
    language: str
    status: str
    summary_verdict: str | None
    compile_error: str | None
    cases: list[CaseVerdictResponse]
