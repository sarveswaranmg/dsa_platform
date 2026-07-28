import uuid
from typing import Any

from pydantic import BaseModel, Field


class GenerationRequest(BaseModel):
    topic_id: uuid.UUID
    difficulty_band: str = Field(pattern="^(easy|medium|hard)$")
    language_targets: list[str] = Field(min_length=1)


class GenerationCreated(BaseModel):
    id: uuid.UUID
    status: str


class GenerationResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    status: str
    attempt: int
    topic_id: uuid.UUID
    difficulty_band: str
    language_targets: list[str]
    question_id: uuid.UUID | None
    question_version_id: uuid.UUID | None
    error: str | None
    discard_log: dict[str, Any] | None
