import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UploadUrlResponse(BaseModel):
    resume_s3_key: str
    upload_url: str


class ProfileCreate(BaseModel):
    resume_s3_key: str = Field(min_length=1)
    github_handle: str | None = None


class ProfileCreated(BaseModel):
    id: uuid.UUID
    status: str


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    status: str
    resume_s3_key: str
    github_handle: str | None
    years_exp: int | None
    domains: list[str] | None
    tech_stack: list[str] | None
    seniority_estimate: str | None
    weak_signals: list[str] | None
    strong_signals: list[str] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
