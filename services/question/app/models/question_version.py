import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class QuestionVersion(UUIDPrimaryKeyMixin, Base):
    """Immutable snapshot of a question's content. Rows referenced by
    questions.published_version_id must never be mutated — grading binds to
    them. No updated_at by design."""

    __tablename__ = "question_versions"
    __table_args__ = (
        UniqueConstraint("question_id", "version_number"),
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int]
    title: Mapped[str] = mapped_column(String(300))
    statement_md: Mapped[str]
    constraints_md: Mapped[str]
    difficulty: Mapped[int]
    time_limit_ms: Mapped[int]
    memory_limit_mb: Mapped[int]
    starter_code: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
