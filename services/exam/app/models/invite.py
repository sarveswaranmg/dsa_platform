import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class InviteStatus(enum.StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    REVOKED = "revoked"


class Invite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable record of an invite. Single-use is enforced atomically in Redis
    (key invite:{jti}); this row is the audit trail the examiner sees."""

    __tablename__ = "invites"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True)
    candidate_email: Mapped[str] = mapped_column(String(320))
    status: Mapped[InviteStatus] = mapped_column(
        Enum(
            InviteStatus,
            name="invite_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=InviteStatus.PENDING,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
