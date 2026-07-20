import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class TestCase(UUIDPrimaryKeyMixin, Base):
    """Metadata only — payloads live in S3 under the recorded keys."""

    __tablename__ = "test_cases"
    __table_args__ = (UniqueConstraint("question_version_id", "ordinal"),)

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    question_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int]
    is_sample: Mapped[bool] = mapped_column(default=False)
    input_s3_key: Mapped[str] = mapped_column(String(512))
    expected_output_s3_key: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
