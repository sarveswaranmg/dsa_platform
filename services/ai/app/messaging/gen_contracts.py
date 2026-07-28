"""Wire contracts for the judge-gen lane. Independent copy of
`services/judge/app/gen_contracts.py` — services never import each other's
code (hard rule); the two copies are kept in sync by field name."""

import enum
import uuid

from pydantic import BaseModel


class Language(enum.StrEnum):
    PYTHON = "python"
    JAVA = "java"
    CPP = "cpp"


class Verdict(enum.StrEnum):
    AC = "AC"
    WA = "WA"
    TLE = "TLE"
    MLE = "MLE"
    RE = "RE"
    CE = "CE"


class CompareMode(enum.StrEnum):
    EXACT = "exact"
    WHITESPACE = "whitespace"


class Limits(BaseModel):
    time_ms: int
    memory_mb: int
    pids: int = 64
    output_bytes: int = 1_000_000


class DiffInputRef(BaseModel):
    ordinal: int
    input_s3_key: str


class DiffJob(BaseModel):
    job_id: uuid.UUID
    org_id: uuid.UUID
    attempt: int
    language: Language
    reference_source: str
    brute_force_source: str
    limits: Limits
    compare_mode: CompareMode = CompareMode.WHITESPACE
    inputs: list[DiffInputRef]
    # Phase 2 Slice 3 (test-case factory): capture the reference's output on
    # agreement too (it becomes a kept test case's expected output), and
    # optionally publish results to a throwaway per-request queue instead of
    # the shared async one (the on-demand synchronous variant).
    capture_agreement_outputs: bool = False
    results_queue: str | None = None
    request_id: str | None = None


class DiffCaseResult(BaseModel):
    ordinal: int
    agree: bool
    reference_verdict: Verdict
    brute_force_verdict: Verdict
    reference_output_b64: str | None = None
    brute_force_output_b64: str | None = None


class DiffStatus(enum.StrEnum):
    COMPLETED = "completed"
    REFERENCE_COMPILE_ERROR = "reference_compile_error"
    BRUTE_FORCE_COMPILE_ERROR = "brute_force_compile_error"


class DiffResult(BaseModel):
    job_id: uuid.UUID
    org_id: uuid.UUID
    attempt: int
    status: DiffStatus
    agreement_pct: float
    compile_error: str | None = None
    cases: list[DiffCaseResult]
    request_id: str | None = None
