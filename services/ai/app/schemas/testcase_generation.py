import uuid
from typing import Any

from pydantic import BaseModel


class TestCaseGenerationRequest(BaseModel):
    question_version_id: uuid.UUID
    synchronous: bool = False


class TestCaseGenerationCreated(BaseModel):
    id: uuid.UUID
    status: str


class TestCaseGenerationResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    status: str
    question_id: uuid.UUID
    question_version_id: uuid.UUID
    synchronous: bool
    kept_case_count: int
    error: str | None
    discard_log: dict[str, Any] | None
