"""Wire contracts for the judge.

The `SubmissionJob` / `VerdictMessage` field names ARE the cross-service
contract (SQS JSON). The exam service owns a duplicate copy of the same shapes
— services never import each other's code (hard rule), so the two copies must
be kept in sync by field name.
"""

import enum
import uuid

from pydantic import BaseModel, Field


class Language(enum.StrEnum):
    PYTHON = "python"
    JAVA = "java"
    CPP = "cpp"


class Verdict(enum.StrEnum):
    AC = "AC"  # accepted
    WA = "WA"  # wrong answer
    TLE = "TLE"  # time limit exceeded
    MLE = "MLE"  # memory limit exceeded
    RE = "RE"  # runtime error
    CE = "CE"  # compile error


class CompareMode(enum.StrEnum):
    EXACT = "exact"
    WHITESPACE = "whitespace"


class Limits(BaseModel):
    time_ms: int = Field(ge=100, le=30_000)
    memory_mb: int = Field(ge=16, le=4_096)
    pids: int = Field(default=64, ge=1, le=512)
    output_bytes: int = Field(default=1_000_000, ge=1_024)


class TestCaseRef(BaseModel):
    __test__ = False  # not a pytest test class despite the name

    ordinal: int
    input_s3_key: str
    expected_output_s3_key: str


class SubmissionJob(BaseModel):
    submission_id: uuid.UUID
    org_id: uuid.UUID
    language: Language
    source: str
    compare_mode: CompareMode = CompareMode.WHITESPACE
    limits: Limits
    cases: list[TestCaseRef]


class CaseResult(BaseModel):
    ordinal: int
    verdict: Verdict
    runtime_ms: int
    memory_kb: int


class SubmissionStatus(enum.StrEnum):
    COMPLETED = "completed"
    COMPILE_ERROR = "compile_error"


class VerdictMessage(BaseModel):
    submission_id: uuid.UUID
    org_id: uuid.UUID
    status: SubmissionStatus
    summary_verdict: Verdict
    compile_error: str | None = None
    cases: list[CaseResult]
