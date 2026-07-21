import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SessionStatus(enum.StrEnum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EXPIRED = "expired"


class ExamSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exam_sessions"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # One session per exam/candidate in Phase 1.
    exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exams.id"), unique=True)
    candidate_email: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(16), default=SessionStatus.IN_PROGRESS.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Server-authoritative deadline = min(started_at + duration, exam.ends_at).
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
