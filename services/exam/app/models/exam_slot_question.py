import enum
import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SlotStatus(enum.StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class ExamSlotQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One AI-generated question slot pinned to a Mode 2 exam (Phase 2 Slice
    4). `topic_id` is a question service id kept as a plain UUID value (no
    cross-service FK — services never share a database); `generation_job_id`
    is likewise ai's opaque `generation_jobs.id`. Phase 1 (manual) exams have
    no rows here at all — `start_session` falls back to sampling in that
    case."""

    __tablename__ = "exam_slot_questions"
    __table_args__ = (UniqueConstraint("exam_id", "ordinal"),)

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int]
    topic_id: Mapped[uuid.UUID] = mapped_column()
    difficulty_band: Mapped[str] = mapped_column(String(20))
    generation_job_id: Mapped[uuid.UUID] = mapped_column()
    # Populated once status=ready.
    question_id: Mapped[uuid.UUID | None] = mapped_column()
    question_version_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default=SlotStatus.PENDING.value)
    error: Mapped[str | None] = mapped_column()
