import uuid

from pydantic import BaseModel, Field

from app.generation.schemas import AvailableTopic, BlueprintSlot


class BlueprintGenerateRequest(BaseModel):
    candidate_profile_id: uuid.UUID
    target_role: str = Field(min_length=1, max_length=120)
    seniority_band: str = Field(min_length=1, max_length=60)
    available_topics: list[AvailableTopic] = Field(min_length=1)


class BlueprintGenerateResponse(BaseModel):
    topic_mix: list[BlueprintSlot]
    total_duration_minutes: int
    rationale: str
