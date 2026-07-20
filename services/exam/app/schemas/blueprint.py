import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TopicMixEntry(BaseModel):
    topic_id: uuid.UUID
    weight: int = Field(ge=1, le=100)
    difficulty_min: int = Field(ge=1, le=5)
    difficulty_max: int = Field(ge=1, le=5)
    question_count: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_difficulty_order(self) -> Self:
        if self.difficulty_min > self.difficulty_max:
            raise ValueError("difficulty_min must be <= difficulty_max")
        return self


class _BlueprintBody(BaseModel):
    target_role: str = Field(min_length=1, max_length=120)
    experience_band: str = Field(min_length=1, max_length=60)
    total_duration_minutes: int = Field(ge=1, le=1440)
    topic_mix: list[TopicMixEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_mix(self) -> Self:
        if sum(e.weight for e in self.topic_mix) != 100:
            raise ValueError("topic_mix weights must sum to 100")
        topic_ids = [e.topic_id for e in self.topic_mix]
        if len(set(topic_ids)) != len(topic_ids):
            raise ValueError("topic_mix must not repeat a topic_id")
        return self


class BlueprintCreate(_BlueprintBody):
    name: str = Field(min_length=1, max_length=200)


class BlueprintUpdate(_BlueprintBody):
    """Full replacement of the versioned content; name is edited separately
    on the identity row."""

    name: str | None = Field(default=None, min_length=1, max_length=200)


class BlueprintVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    blueprint_id: uuid.UUID
    version_number: int
    target_role: str
    experience_band: str
    total_duration_minutes: int
    topic_mix: list[TopicMixEntry]
    created_at: datetime


class BlueprintResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    current_version: BlueprintVersionResponse
