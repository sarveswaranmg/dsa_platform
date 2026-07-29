import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
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
    # Adaptive difficulty engine (Phase 2 Slice 5) — set after each graded
    # verdict from ai's /internal/difficulty/signal response. Observability
    # only this slice: nothing yet changes what question the candidate sees.
    current_difficulty: Mapped[float | None] = mapped_column()
    current_difficulty_band: Mapped[str | None] = mapped_column(String(16))
    # Hiring signal report (Phase 2 Slice 8) — a served-read cache of ai's
    # own hiring_reports row, pushed here via POST
    # /internal/sessions/{id}/report once evaluation completes. NULL until
    # then; ai's table stays the source of truth.
    hiring_report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    hiring_report_recommendation: Mapped[str | None] = mapped_column(String(16))
    hiring_report_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
