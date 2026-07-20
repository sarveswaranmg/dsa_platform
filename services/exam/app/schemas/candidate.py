import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ExchangeRequest(BaseModel):
    invite_token: str = Field(min_length=1)
    google_id_token: str = Field(min_length=1)


class ExchangeResponse(BaseModel):
    exam_token: str
    token_type: str = "bearer"
    exam_id: uuid.UUID
    candidate_email: EmailStr
    starts_at: datetime
    ends_at: datetime


class CandidateExamResponse(BaseModel):
    exam_id: uuid.UUID
    org_id: uuid.UUID
    candidate_email: EmailStr
    blueprint_version_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
