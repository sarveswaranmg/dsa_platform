import enum
import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProfileStatus(enum.StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class CandidateProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Owned entirely by the ai service — no FK from/to any other service's
    tables (services never share a database). `exam` will hold `profile_id`
    as a plain UUID value once Mode 2 scheduling (Phase 2 Slice 4) wires the
    two together."""

    __tablename__ = "candidate_profiles"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(20), default=ProfileStatus.QUEUED)
    resume_s3_key: Mapped[str] = mapped_column(String(512))
    github_handle: Mapped[str | None] = mapped_column(String(200))

    # Populated once status=ready.
    years_exp: Mapped[int | None] = mapped_column()
    domains: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    tech_stack: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    seniority_estimate: Mapped[str | None] = mapped_column(String(50))
    weak_signals: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    strong_signals: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    # Populated once status=failed.
    error: Mapped[str | None] = mapped_column(Text)
