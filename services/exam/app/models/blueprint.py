import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Blueprint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "blueprints"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(200))
    # use_alter: circular FK pair with blueprint_versions.blueprint_id.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("blueprint_versions.id", use_alter=True)
    )
