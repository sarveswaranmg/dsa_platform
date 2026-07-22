"""Exam-side copy of the judge wire contracts.

The judge service owns the authoritative shapes in its own contracts.py;
services never import each other's code (hard rule), so these are kept in sync
by field name only. Only the fields the exam side produces/consumes are
modelled here.
"""

import enum
import uuid

from pydantic import BaseModel


class TestCaseRef(BaseModel):
    ordinal: int
    input_s3_key: str
    expected_output_s3_key: str


class JobLimits(BaseModel):
    time_ms: int
    memory_mb: int


class SubmissionJob(BaseModel):
    submission_id: uuid.UUID
    org_id: uuid.UUID
    language: str
    source: str
    compare_mode: str
    limits: JobLimits
    cases: list[TestCaseRef]
    request_id: str | None = None


class CaseResult(BaseModel):
    ordinal: int
    verdict: str
    runtime_ms: int
    memory_kb: int


class VerdictStatus(enum.StrEnum):
    COMPLETED = "completed"
    COMPILE_ERROR = "compile_error"


class VerdictMessage(BaseModel):
    submission_id: uuid.UUID
    org_id: uuid.UUID
    status: VerdictStatus
    summary_verdict: str
    compile_error: str | None = None
    cases: list[CaseResult]
    request_id: str | None = None
