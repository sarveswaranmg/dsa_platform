import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CandidateContext, get_candidate_context
from app.clients.question_service import QuestionServiceClient, get_question_client
from app.core.exceptions import NotFound
from app.core.redis import get_redis
from app.db.session import get_db
from app.messaging.sqs import QueuePublisher, get_publisher
from app.models.case_verdict import CaseVerdict
from app.models.submission import Submission
from app.oidc.google import GoogleOIDCVerifier, get_oidc_verifier
from app.repositories import exams as exams_repo
from app.schemas.candidate import (
    CandidateExamResponse,
    ExchangeRequest,
    ExchangeResponse,
)
from app.schemas.submission import (
    CaseVerdictResponse,
    SubmissionResponse,
    SubmitRequest,
)
from app.services import candidate_auth as candidate_auth_service
from app.services import submissions as submissions_service

router = APIRouter(prefix="/candidate", tags=["candidate"])

DB = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
VerifierDep = Annotated[GoogleOIDCVerifier, Depends(get_oidc_verifier)]
CandidateCtx = Annotated[CandidateContext, Depends(get_candidate_context)]
QuestionClient = Annotated[QuestionServiceClient, Depends(get_question_client)]
PublisherDep = Annotated[QueuePublisher, Depends(get_publisher)]


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


def _submission_response(
    submission: Submission, cases: list[CaseVerdict]
) -> SubmissionResponse:
    return SubmissionResponse(
        id=submission.id,
        exam_id=submission.exam_id,
        question_version_id=submission.question_version_id,
        language=submission.language,
        status=submission.status,
        summary_verdict=submission.summary_verdict,
        compile_error=submission.compile_error,
        cases=[CaseVerdictResponse.model_validate(c) for c in cases],
    )


@router.post("/submissions", response_model=SubmissionResponse, status_code=201)
async def create_submission(
    body: SubmitRequest,
    ctx: CandidateCtx,
    session: DB,
    question_client: QuestionClient,
    publisher: PublisherDep,
) -> SubmissionResponse:
    submission = await submissions_service.create_and_enqueue(
        session,
        question_client,
        publisher,
        org_id=ctx.org_id,
        exam_id=ctx.exam_id,
        question_version_id=body.question_version_id,
        language=body.language,
        source=body.source,
    )
    return _submission_response(submission, [])


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: uuid.UUID, ctx: CandidateCtx, session: DB
) -> SubmissionResponse:
    submission, cases = await submissions_service.get_submission_detail(
        session, org_id=ctx.org_id, submission_id=submission_id
    )
    return _submission_response(submission, cases)


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
