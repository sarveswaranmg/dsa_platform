import uuid
from typing import Any

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SessionEvaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per (session, ordinal) — Phase 2 Slice 7, see
    docs/design-ai-evaluation.md. `session_id`/`question_id`/
    `question_version_id` are exam/question service ids kept as plain UUID
    values — no cross-service FK (services never share a database)."""

    __tablename__ = "session_evaluations"
    __table_args__ = (UniqueConstraint("session_id", "ordinal"),)

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(index=True)
    ordinal: Mapped[int]
    question_id: Mapped[uuid.UUID] = mapped_column()
    question_version_id: Mapped[uuid.UUID] = mapped_column()
    # Null when the ordinal was assigned but never submitted to.
    complexity: Mapped[str | None] = mapped_column(String(20))
    approach: Mapped[str | None] = mapped_column(String(64))
    partial_score: Mapped[float] = mapped_column()
    behavioural_signals: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
