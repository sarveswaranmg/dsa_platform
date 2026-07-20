from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CandidateContext, get_candidate_context
from app.core.exceptions import NotFound
from app.core.redis import get_redis
from app.db.session import get_db
from app.oidc.google import GoogleOIDCVerifier, get_oidc_verifier
from app.repositories import exams as exams_repo
from app.schemas.candidate import (
    CandidateExamResponse,
    ExchangeRequest,
    ExchangeResponse,
)
from app.services import candidate_auth as candidate_auth_service

router = APIRouter(prefix="/candidate", tags=["candidate"])

DB = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
VerifierDep = Annotated[GoogleOIDCVerifier, Depends(get_oidc_verifier)]


@router.post("/auth/exchange", response_model=ExchangeResponse)
async def exchange(
    body: ExchangeRequest, session: DB, redis: RedisDep, verifier: VerifierDep
) -> ExchangeResponse:
    exam, exam_token = await candidate_auth_service.exchange(
        session,
        redis,
        verifier,
        invite_token=body.invite_token,
        google_id_token=body.google_id_token,
    )
    return ExchangeResponse(
        exam_token=exam_token,
        exam_id=exam.id,
        candidate_email=exam.candidate_email,
        starts_at=exam.starts_at,
        ends_at=exam.ends_at,
    )


@router.get("/exam", response_model=CandidateExamResponse)
async def get_current_exam(
    ctx: Annotated[CandidateContext, Depends(get_candidate_context)], session: DB
) -> CandidateExamResponse:
    # Proves the exam-scoped candidate token plane; the full session lifecycle
    # lands in Slice 6.
    exam = await exams_repo.get_by_id(session, org_id=ctx.org_id, exam_id=ctx.exam_id)
    if exam is None:
        raise NotFound("Exam not found")
    return CandidateExamResponse(
        exam_id=exam.id,
        org_id=exam.org_id,
        candidate_email=exam.candidate_email,
        blueprint_version_id=exam.blueprint_version_id,
        starts_at=exam.starts_at,
        ends_at=exam.ends_at,
    )
