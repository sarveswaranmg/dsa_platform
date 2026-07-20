import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.question import QuestionStatus


class Language(enum.StrEnum):
    """Phase 1 judge languages."""

    PYTHON = "python"
    JAVA = "java"
    CPP = "cpp"


class QuestionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    statement_md: str = Field(min_length=1)
    constraints_md: str = ""
    difficulty: int = Field(ge=1, le=5)
    time_limit_ms: int = Field(ge=100, le=30_000)
    memory_limit_mb: int = Field(ge=16, le=4_096)
    starter_code: dict[Language, str] = Field(default_factory=dict)
    topic_ids: list[uuid.UUID] = Field(default_factory=list)


class QuestionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    statement_md: str | None = Field(default=None, min_length=1)
    constraints_md: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    time_limit_ms: int | None = Field(default=None, ge=100, le=30_000)
    memory_limit_mb: int | None = Field(default=None, ge=16, le=4_096)
    starter_code: dict[Language, str] | None = None
    topic_ids: list[uuid.UUID] | None = None


class QuestionVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    version_number: int
    title: str
    statement_md: str
    constraints_md: str
    difficulty: int
    time_limit_ms: int
    memory_limit_mb: int
    starter_code: dict[str, str]
    created_at: datetime


class QuestionResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    status: QuestionStatus
    published_version_id: uuid.UUID | None
    current_version: QuestionVersionResponse
    topic_ids: list[uuid.UUID]


class QuestionListItem(BaseModel):
    id: uuid.UUID
    status: QuestionStatus
    title: str
    difficulty: int
    version_number: int
