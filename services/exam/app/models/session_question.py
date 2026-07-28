import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class SessionQuestion(UUIDPrimaryKeyMixin, Base):
    """One assigned question in a candidate's session. The version is pinned at
    start, so a submission always grades against the version the candidate saw."""

    __tablename__ = "session_questions"
    __table_args__ = (UniqueConstraint("session_id", "ordinal"),)

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int]
    question_id: Mapped[uuid.UUID] = mapped_column()
    question_version_id: Mapped[uuid.UUID] = mapped_column()
    # Set lazily on first GET of this question's content (Phase 2 Slice 5) —
    # the adaptive difficulty engine needs a real per-question time budget.
    shown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
