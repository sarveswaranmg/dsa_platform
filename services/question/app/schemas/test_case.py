import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TestCaseCreate(BaseModel):
    ordinal: int | None = Field(default=None, ge=1)
    is_sample: bool = False


class TestCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_version_id: uuid.UUID
    ordinal: int
    is_sample: bool
    input_s3_key: str
    expected_output_s3_key: str
    created_at: datetime


class TestCaseCreateResponse(TestCaseResponse):
    upload_input_url: str
    upload_output_url: str


class TestCaseDownloadResponse(TestCaseResponse):
    input_url: str
    output_url: str
