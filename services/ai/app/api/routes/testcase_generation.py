import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, Role, require_role
from app.clients.question_service import QuestionServiceClient, get_question_client
from app.core.exceptions import NotFound
from app.db.session import get_db
from app.llm.client import LLMClient, get_llm_client
from app.messaging.sqs import QueuePublisher, get_publisher
from app.repositories import test_case_generation_jobs as test_case_generation_jobs_repo
from app.schemas.testcase_generation import (
    TestCaseGenerationCreated,
    TestCaseGenerationRequest,
    TestCaseGenerationResponse,
)
from app.services import testcase_generation as testcase_generation_service

router = APIRouter(prefix="/test-cases/generate", tags=["testcase-generation"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
ReaderCtx = Annotated[AuthContext, Depends(require_role())]
LLM = Annotated[LLMClient, Depends(get_llm_client)]
Publisher = Annotated[QueuePublisher, Depends(get_publisher)]
QuestionClient = Annotated[QuestionServiceClient, Depends(get_question_client)]


@router.post("", response_model=TestCaseGenerationCreated, status_code=201)
async def create_testcase_generation(
    body: TestCaseGenerationRequest,
    ctx: WriterCtx,
    session: DB,
    llm_client: LLM,
    publisher: Publisher,
    question_client: QuestionClient,
) -> TestCaseGenerationCreated:
    job = await testcase_generation_service.start_factory_job(
        session,
        org_id=ctx.org_id,
        question_version_id=body.question_version_id,
        synchronous=body.synchronous,
        llm_client=llm_client,
        publisher=publisher,
        question_client=question_client,
    )
    return TestCaseGenerationCreated(id=job.id, status=job.status)


@router.get("/{job_id}", response_model=TestCaseGenerationResponse)
async def get_testcase_generation(
    job_id: uuid.UUID, ctx: ReaderCtx, session: DB
) -> TestCaseGenerationResponse:
    job = await test_case_generation_jobs_repo.get_by_id(session, org_id=ctx.org_id, job_id=job_id)
    if job is None:
        raise NotFound("Test-case generation job not found")
    return TestCaseGenerationResponse(
        id=job.id,
        org_id=job.org_id,
        status=job.status,
        question_id=job.question_id,
        question_version_id=job.question_version_id,
        synchronous=job.synchronous,
        kept_case_count=job.kept_case_count,
        error=job.error,
        discard_log=job.discard_log,
    )
