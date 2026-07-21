import enum
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SubmissionStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPILE_ERROR = "compile_error"
    ERROR = "error"


class Submission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "submissions"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exams.id"), index=True)
    # Nullable until Slice 6 wires the session lifecycle around submissions.
    session_id: Mapped[uuid.UUID | None] = mapped_column()
    question_version_id: Mapped[uuid.UUID] = mapped_column()
    language: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(Text)
    compare_mode: Mapped[str] = mapped_column(String(16))
    # Stored as a plain string (StrEnum values); avoids a Postgres enum + the
    # migration bookkeeping that comes with it.
    status: Mapped[str] = mapped_column(String(16), default=SubmissionStatus.QUEUED.value)
    summary_verdict: Mapped[str | None] = mapped_column(String(4))
    compile_error: Mapped[str | None] = mapped_column(Text)
