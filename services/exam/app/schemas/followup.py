import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FollowupRequest(BaseModel):
    ordinal: int = Field(ge=1)
    modified_constraints_md: str = Field(min_length=1)


class FollowupResponse(BaseModel):
    previous_version_id: uuid.UUID
    new_version_id: uuid.UUID


class SessionEventResponse(BaseModel):
    seq: int
    type: str
    payload: dict[str, Any]
    question_version_id: uuid.UUID | None
    created_at: datetime
