import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

from app.models.exam import ExamStatus
from app.models.invite import InviteStatus


class ExamScheduleRequest(BaseModel):
    candidate_email: EmailStr
    blueprint_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class ExamScheduleAiRequest(BaseModel):
    candidate_email: EmailStr
    candidate_profile_id: uuid.UUID
    target_role: str
    seniority_band: str
    language_targets: list[str]
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class SlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordinal: int
    topic_id: uuid.UUID
    difficulty_band: str
    question_id: uuid.UUID | None
    question_version_id: uuid.UUID | None
    status: str
    error: str | None


class InviteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: InviteStatus
    candidate_email: EmailStr
    consumed_at: datetime | None


class ExamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    blueprint_id: uuid.UUID
    blueprint_version_id: uuid.UUID
    candidate_email: EmailStr
    starts_at: datetime
    ends_at: datetime
    status: ExamStatus
    # Mode 2 only: null for Phase 1 (manually-authored) exams.
    review_deadline_at: datetime | None = None
    slots: list[SlotResponse] = []


class ExamScheduleResponse(ExamResponse):
    invite: InviteSummary | None
    # Present in dev only (email_backend=console) so the flow is walkable
    # without a real inbox.
    invite_link: str | None = None


class ScheduleAiCreated(BaseModel):
    id: uuid.UUID
    status: ExamStatus
