import enum
import uuid

from sqlalchemy import Column, Enum, ForeignKey, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class QuestionStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


question_topics = Table(
    "question_topics",
    Base.metadata,
    Column(
        "question_id",
        ForeignKey("questions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("topic_id", ForeignKey("topics.id"), primary_key=True),
)


class Question(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "questions"

    org_id: Mapped[uuid.UUID] = mapped_column(index=True)
    status: Mapped[QuestionStatus] = mapped_column(
        Enum(
            QuestionStatus,
            name="question_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=QuestionStatus.DRAFT,
    )
    # use_alter: circular FK pair with question_versions.question_id.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("question_versions.id", use_alter=True)
    )
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("question_versions.id", use_alter=True)
    )
