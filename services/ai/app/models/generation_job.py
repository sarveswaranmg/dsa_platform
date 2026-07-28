import enum
import uuid
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GenerationStatus(enum.StrEnum):
    QUEUED = "queued"
    DRAFTING = "drafting"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Owned entirely by the ai service. `topic_id` and `question_version_id`
    are question service ids kept as plain UUID values — no cross-service FK
    (services never share a database). `reference_solution`/
    `brute_force_solution` stay here (not in the question service) so a
    later Slice 3 test-case factory can fetch them back from `ai` by
    `question_version_id`."""

    __tablename__ = "generation_jobs"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    topic_id: Mapped[uuid.UUID] = mapped_column()
    difficulty_band: Mapped[str] = mapped_column(String(20))
    language_targets: Mapped[list[str]] = mapped_column(ARRAY(String))
    status: Mapped[str] = mapped_column(String(20), default=GenerationStatus.QUEUED)
    attempt: Mapped[int] = mapped_column(default=0)

    # Set once, on the first (drafting) step; never regenerated on retry.
    draft: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Current/winning attempt's solutions.
    reference_solution: Mapped[str | None] = mapped_column(Text)
    brute_force_solution: Mapped[str | None] = mapped_column(Text)

    # Populated once status=succeeded.
    question_version_id: Mapped[uuid.UUID | None] = mapped_column()
    question_id: Mapped[uuid.UUID | None] = mapped_column()

    # Populated once status=failed: the final attempt's disagreeing cases.
    discard_log: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
