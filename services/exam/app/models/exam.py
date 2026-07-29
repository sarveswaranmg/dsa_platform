import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExamStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    # Mode 2 (profile-driven, Phase 2 Slice 4) only — Mode 1 exams go
    # straight to SCHEDULED. PENDING_GENERATION: AI question generation is
    # in flight for one or more slots. PENDING_REVIEW: all slots ready,
    # waiting on examiner confirm (or the review deadline) before the
    # invite goes out. GENERATION_FAILED: at least one slot failed; an
    # examiner override moves it back to PENDING_GENERATION.
    PENDING_GENERATION = "pending_generation"
    PENDING_REVIEW = "pending_review"
    GENERATION_FAILED = "generation_failed"


class Exam(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exams"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    blueprint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blueprints.id"))
    # Pinned at schedule time so a later blueprint edit never moves this exam.
    blueprint_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blueprint_versions.id")
    )
    candidate_email: Mapped[str] = mapped_column(String(320), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[ExamStatus] = mapped_column(
        Enum(
            ExamStatus,
            name="exam_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ExamStatus.SCHEDULED,
    )
    # Mode 2 only: set once every slot reaches `ready`; a lazy check on the
    # next read (GET/confirm/regenerate) auto-confirms once this passes.
    review_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Mode 2 only: the language targets requested at schedule-ai time, kept
    # here (once per exam, shared by every slot) so a later slot
    # regeneration can re-call ai's generate_question with the same targets.
    language_targets: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    # Mode 2 only (Phase 2 Slice 8) — the ai-service profile id that drove
    # this exam's blueprint proposal, kept for the hiring report's seniority
    # match. NULL for Mode 1 (manual) exams.
    candidate_profile_id: Mapped[uuid.UUID | None] = mapped_column()
