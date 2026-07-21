import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
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
