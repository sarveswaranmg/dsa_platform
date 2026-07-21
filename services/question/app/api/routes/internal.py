"""Internal, service-to-service endpoints — NOT exposed through the gateway
(Slice 9 keeps the /internal prefix off the public route table). No examiner
auth: reachable only on the trusted compose network. Used by the exam service
to resolve test-case S3 keys for a pinned question version when building a
judge submission job.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories import test_cases as test_cases_repo

router = APIRouter(prefix="/internal", tags=["internal"])

DB = Annotated[AsyncSession, Depends(get_db)]


class InternalTestCase(BaseModel):
    ordinal: int
    is_sample: bool
    input_s3_key: str
    expected_output_s3_key: str


@router.get(
    "/question-versions/{version_id}/test-cases",
    response_model=list[InternalTestCase],
)
async def list_version_test_cases(
    version_id: uuid.UUID, org_id: uuid.UUID, session: DB
) -> list[InternalTestCase]:
    # org_id is still required — multi-tenancy is structural even internally.
    rows = await test_cases_repo.list_by_version(
        session, org_id=org_id, question_version_id=version_id
    )
    return [
        InternalTestCase(
            ordinal=tc.ordinal,
            is_sample=tc.is_sample,
            input_s3_key=tc.input_s3_key,
            expected_output_s3_key=tc.expected_output_s3_key,
        )
        for tc in rows
    ]
