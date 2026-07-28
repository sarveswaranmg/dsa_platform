"""Wire contracts for the judge-gen lane (differential testing of a
reference vs. brute-force solution during AI question generation — Phase 2
Slice 2). Independent of `contracts.py`'s judge-live shapes by design
(services never import each other's code — the ai service keeps its own
copies, kept in sync by field name), but reuses the enums/Limits types
since those aren't wire-contract-specific.
"""

import enum
import uuid

from pydantic import BaseModel

from app.contracts import CompareMode, Language, Limits, Verdict


class DiffInputRef(BaseModel):
    ordinal: int
    input_s3_key: str  # lives in the ai service's bucket, not question's


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
    # Phase 2 Slice 3 (test-case factory): the reference's output is only
    # captured on disagreement by default (small discard log); the factory
    # needs it on agreement too, since that becomes a kept test case's
    # expected output. Left False for Slice 2's question-generation jobs
    # (up to 100 inputs) to avoid risking the 256KB SQS message cap there.
    capture_agreement_outputs: bool = False
    # Slice 3's on-demand (synchronous) variant publishes results to a
    # throwaway per-request queue instead of the shared async one, so it
    # never contends with the persistent gen-result consumer.
    results_queue: str | None = None
    request_id: str | None = None


class DiffCaseResult(BaseModel):
    ordinal: int
    agree: bool
    reference_verdict: Verdict
    brute_force_verdict: Verdict
    # Always populated on disagreement (truncated) — feeds ai's discard
    # log. Also populated on agreement when the job set
    # capture_agreement_outputs (it becomes a kept test case's expected
    # output; see Slice 3's test-case factory).
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
