import uuid

from pydantic import BaseModel, Field

from app.difficulty.rules import ComplexityHint


class DifficultySignalRequest(BaseModel):
    session_id: uuid.UUID
    question_version_id: uuid.UUID
    time_elapsed_pct: float = Field(ge=0)
    verdict: str
    complexity_hint: ComplexityHint | None = None


class DifficultySignalResponse(BaseModel):
    difficulty: float
    difficulty_band: str
