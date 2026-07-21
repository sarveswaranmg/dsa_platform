import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class CaseVerdict(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "case_verdicts"
    # One verdict per (submission, ordinal) — the idempotency key that makes
    # duplicate verdict deliveries a no-op.
    __table_args__ = (UniqueConstraint("submission_id", "ordinal"),)

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int]
    verdict: Mapped[str] = mapped_column(String(4))
    runtime_ms: Mapped[int]
    memory_kb: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
