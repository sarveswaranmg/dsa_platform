import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, Role, require_role
from app.db.session import get_db
from app.schemas.test_case import (
    TestCaseCreate,
    TestCaseCreateResponse,
    TestCaseDownloadResponse,
    TestCaseResponse,
)
from app.services import test_cases as test_cases_service

router = APIRouter(prefix="/questions/{question_id}/test-cases", tags=["test-cases"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
ReaderCtx = Annotated[AuthContext, Depends(require_role())]


@router.post("", response_model=TestCaseCreateResponse, status_code=201)
async def create_test_case(
    question_id: uuid.UUID, body: TestCaseCreate, ctx: WriterCtx, session: DB
) -> TestCaseCreateResponse:
    test_case, input_url, output_url = await test_cases_service.create_test_case(
        session,
        org_id=ctx.org_id,
        question_id=question_id,
        ordinal=body.ordinal,
        is_sample=body.is_sample,
    )
    base = TestCaseResponse.model_validate(test_case)
    return TestCaseCreateResponse(
        **base.model_dump(), upload_input_url=input_url, upload_output_url=output_url
    )


@router.get("", response_model=list[TestCaseDownloadResponse])
async def list_test_cases(
    question_id: uuid.UUID, ctx: ReaderCtx, session: DB
) -> list[TestCaseDownloadResponse]:
    rows = await test_cases_service.list_test_cases(
        session, org_id=ctx.org_id, question_id=question_id
    )
    return [
        TestCaseDownloadResponse(
            **TestCaseResponse.model_validate(tc).model_dump(),
            input_url=input_url,
            output_url=output_url,
        )
        for tc, input_url, output_url in rows
    ]


@router.delete("/{test_case_id}", status_code=204)
async def delete_test_case(
    question_id: uuid.UUID, test_case_id: uuid.UUID, ctx: WriterCtx, session: DB
) -> None:
    await test_cases_service.delete_test_case(
        session, org_id=ctx.org_id, question_id=question_id, test_case_id=test_case_id
    )
