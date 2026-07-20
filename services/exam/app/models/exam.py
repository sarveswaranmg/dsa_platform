import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExamStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


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
