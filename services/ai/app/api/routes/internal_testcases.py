import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.question_service import QuestionServiceClient, get_question_client
from app.db.session import get_db
from app.llm.client import LLMClient, get_llm_client
from app.messaging.sqs import QueuePublisher, get_publisher
from app.schemas.testcase_generation import TestCaseGenerationCreated
from app.services import testcase_generation as testcase_generation_service

# Unauthenticated (trusted-network-only), same convention as this service's
# other /internal/... routes — the caller is exam's mid-exam proctor
# follow-up flow (Phase 2 Slice 6), which has no ADMIN/AUTHOR examiner token
# to forward (unlike the examiner-facing POST /test-cases/generate). Blocked
# at the gateway edge (services/gateway/app/routing.py: Route("/internal", ...)).
router = APIRouter(prefix="/internal/test-cases", tags=["internal"])

DB = Annotated[AsyncSession, Depends(get_db)]
LLM = Annotated[LLMClient, Depends(get_llm_client)]
Publisher = Annotated[QueuePublisher, Depends(get_publisher)]
QuestionClient = Annotated[QuestionServiceClient, Depends(get_question_client)]


class InternalTestCaseGenerationRequest(BaseModel):
    org_id: uuid.UUID
    question_version_id: uuid.UUID
    source_question_id: uuid.UUID


@router.post("/generate", response_model=TestCaseGenerationCreated, status_code=201)
async def generate(
    body: InternalTestCaseGenerationRequest,
    session: DB,
    llm_client: LLM,
    publisher: Publisher,
    question_client: QuestionClient,
) -> TestCaseGenerationCreated:
    # A follow-up needs the result inline (to attach test cases before
    # publishing), so this always runs the synchronous variant regardless
    # of caller input — there's no async job-polling story for this path.
    job = await testcase_generation_service.start_factory_job(
        session,
        org_id=body.org_id,
        question_version_id=body.question_version_id,
        synchronous=True,
        llm_client=llm_client,
        publisher=publisher,
        question_client=question_client,
        source_question_id=body.source_question_id,
    )
    return TestCaseGenerationCreated(id=job.id, status=job.status)
