import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, Role, require_role
from app.core.exceptions import NotFound
from app.db.session import get_db
from app.llm.client import LLMClient, get_llm_client
from app.messaging.sqs import QueuePublisher, get_publisher
from app.repositories import generation_jobs as generation_jobs_repo
from app.schemas.generation import GenerationCreated, GenerationRequest, GenerationResponse
from app.services import generation as generation_service

router = APIRouter(prefix="/questions/generate", tags=["generation"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
ReaderCtx = Annotated[AuthContext, Depends(require_role())]
LLM = Annotated[LLMClient, Depends(get_llm_client)]
Publisher = Annotated[QueuePublisher, Depends(get_publisher)]


@router.post("", response_model=GenerationCreated, status_code=201)
async def create_generation(
    body: GenerationRequest, ctx: WriterCtx, session: DB, llm_client: LLM, publisher: Publisher
) -> GenerationCreated:
    job = await generation_service.start_generation(
        session,
        org_id=ctx.org_id,
        topic_id=body.topic_id,
        difficulty_band=body.difficulty_band,
        language_targets=body.language_targets,
        llm_client=llm_client,
        publisher=publisher,
    )
    return GenerationCreated(id=job.id, status=job.status)


@router.get("/{job_id}", response_model=GenerationResponse)
async def get_generation(job_id: uuid.UUID, ctx: ReaderCtx, session: DB) -> GenerationResponse:
    job = await generation_jobs_repo.get_by_id(session, org_id=ctx.org_id, job_id=job_id)
    if job is None:
        raise NotFound("Generation job not found")
    return GenerationResponse(
        id=job.id,
        org_id=job.org_id,
        status=job.status,
        attempt=job.attempt,
        topic_id=job.topic_id,
        difficulty_band=job.difficulty_band,
        language_targets=job.language_targets,
        question_id=job.question_id,
        question_version_id=job.question_version_id,
        error=job.error,
        discard_log=job.discard_log,
    )
