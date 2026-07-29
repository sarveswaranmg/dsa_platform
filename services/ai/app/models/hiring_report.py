import uuid
from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HiringReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Owned entirely by the ai service — the source of truth this consumer
    upserts into (Phase 2 Slice 8); exam's `ExamSession.hiring_report_json`
    is a served-read cache pushed via POST /internal/sessions/{id}/report."""

    __tablename__ = "hiring_reports"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    recommendation: Mapped[str] = mapped_column(String(16))
    score: Mapped[float] = mapped_column()
