import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.examiner import Role


class ExaminerCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: Role


class ExaminerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    email: EmailStr
    role: Role
    totp_enabled: bool
    is_active: bool
    created_at: datetime


class ExaminerCreateResponse(ExaminerResponse):
    totp_secret: str
    totp_provisioning_uri: str
