from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Org(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orgs"

    name: Mapped[str] = mapped_column(String(200))
