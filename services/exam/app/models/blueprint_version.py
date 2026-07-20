import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class BlueprintVersion(UUIDPrimaryKeyMixin, Base):
    """Immutable snapshot of a blueprint's content. Sampling binds to a
    version id so an assigned question set is reproducible. No updated_at."""

    __tablename__ = "blueprint_versions"
    __table_args__ = (UniqueConstraint("blueprint_id", "version_number"),)

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blueprints.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int]
    target_role: Mapped[str] = mapped_column(String(120))
    experience_band: Mapped[str] = mapped_column(String(60))
    total_duration_minutes: Mapped[int]
    # List of {topic_id, weight, difficulty_min, difficulty_max, question_count}.
    topic_mix: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
