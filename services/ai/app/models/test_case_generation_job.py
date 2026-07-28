import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TestCaseGenerationStatus(enum.StrEnum):
    QUEUED = "queued"
    GENERATING = "generating"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TestCaseGenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Owned entirely by the ai service (Phase 2 Slice 3). A separate table
    from `generation_jobs`, not a reuse of its `discard_log` — that row's
    status is already terminal (`succeeded`) by the time a factory job runs
    against it, and overloading one row with two independent job lifecycles
    would conflate two different concerns (see
    docs/design-testcase-factory.md). `question_id`/`question_version_id`/
    `generation_job_id` are plain UUID values, no cross-service or
    cross-table FK (services never share a database; this repo's convention
    for "same service, different table" cross-references is a plain column
    too, matching e.g. `GenerationJob.topic_id`)."""

    __tablename__ = "test_case_generation_jobs"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    question_id: Mapped[uuid.UUID] = mapped_column()
    question_version_id: Mapped[uuid.UUID] = mapped_column()
    generation_job_id: Mapped[uuid.UUID] = mapped_column()
    synchronous: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default=TestCaseGenerationStatus.QUEUED)

    # Populated once status=succeeded (may be 0 — a factory run keeping no
    # cases still succeeded; there's no retry concept in this slice).
    kept_case_count: Mapped[int] = mapped_column(default=0)

    # Disagreeing candidates from the differential pass, if any.
    discard_log: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
