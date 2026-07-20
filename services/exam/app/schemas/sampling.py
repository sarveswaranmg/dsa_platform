import uuid

from pydantic import BaseModel, Field


class SampleRequest(BaseModel):
    # Stable per-candidate identifier (e.g. invited email). Same key + same
    # blueprint version → identical question set.
    candidate_key: str = Field(min_length=1, max_length=320)


class TopicSelection(BaseModel):
    topic_id: uuid.UUID
    difficulty_min: int
    difficulty_max: int
    question_ids: list[uuid.UUID]


class SampleResponse(BaseModel):
    blueprint_id: uuid.UUID
    blueprint_version_id: uuid.UUID
    candidate_key: str
    total_duration_minutes: int
    total_questions: int
    selections: list[TopicSelection]
