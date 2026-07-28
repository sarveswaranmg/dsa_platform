import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class SessionEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only event stream for a candidate session (Phase 2 Slice 6) —
    the full session becomes replayable. No updated_at: an event is never
    edited once written."""

    __tablename__ = "session_events"
    __table_args__ = (UniqueConstraint("session_id", "seq"),)

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int]
    # question_assigned | code_snapshot | submission | verdict | followup_pushed
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    question_version_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
