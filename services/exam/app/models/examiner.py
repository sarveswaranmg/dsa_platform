import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Role(enum.StrEnum):
    ADMIN = "admin"
    AUTHOR = "author"
    PROCTOR = "proctor"
    REVIEWER = "reviewer"


class Examiner(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "examiners"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="examiner_role", values_callable=lambda e: [m.value for m in e])
    )
    totp_secret: Mapped[str] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
