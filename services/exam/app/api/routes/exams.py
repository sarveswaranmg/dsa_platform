import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_role
from app.clients.ai_service import AiServiceClient, get_ai_client
from app.clients.question_service import QuestionServiceClient, get_question_client
from app.core.config import get_settings
from app.core.exceptions import NotFound
from app.core.redis import get_redis
from app.db.session import get_db
from app.models.exam import Exam, ExamStatus
from app.models.examiner import Role
from app.notifications.email import EmailSender, get_email_sender
from app.repositories import exam_slot_questions as slots_repo
from app.repositories import exams as exams_repo
from app.schemas.exam import (
    ExamResponse,
    ExamScheduleAiRequest,
    ExamScheduleRequest,
    ExamScheduleResponse,
    InviteSummary,
    ScheduleAiCreated,
    SlotResponse,
)
from app.services import ai_scheduling as ai_scheduling_service
from app.services import scheduling as scheduling_service

router = APIRouter(prefix="/exams", tags=["exams"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
ReaderCtx = Annotated[AuthContext, Depends(require_role())]
RedisDep = Annotated[Redis, Depends(get_redis)]
EmailDep = Annotated[EmailSender, Depends(get_email_sender)]
AiClient = Annotated[AiServiceClient, Depends(get_ai_client)]
QuestionClient = Annotated[QuestionServiceClient, Depends(get_question_client)]


async def _exam_response_kwargs(
    session: AsyncSession, org_id: uuid.UUID, exam: Exam
) -> dict[str, Any]:
    slots = await slots_repo.list_by_exam(session, org_id=org_id, exam_id=exam.id)
    dump = ExamResponse.model_validate(exam).model_dump()
    dump["slots"] = [SlotResponse.model_validate(s) for s in slots]
    return dump


@router.post("", response_model=ExamScheduleResponse, status_code=201)
async def schedule_exam(
    body: ExamScheduleRequest,
    ctx: WriterCtx,
    session: DB,
    redis: RedisDep,
    email_sender: EmailDep,
) -> ExamScheduleResponse:
    exam, invite, link = await scheduling_service.schedule_exam(
        session,
        redis,
        email_sender,
        org_id=ctx.org_id,
        candidate_email=body.candidate_email,
        blueprint_id=body.blueprint_id,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    # Only surface the raw link in dev (console email backend).
    show_link = get_settings().email_backend == "console"
    return ExamScheduleResponse(
        **await _exam_response_kwargs(session, ctx.org_id, exam),
        invite=InviteSummary.model_validate(invite),
        invite_link=link if show_link else None,
    )


@router.post("/schedule-ai", response_model=ScheduleAiCreated, status_code=201)
async def schedule_ai_exam(
    body: ExamScheduleAiRequest,
    ctx: WriterCtx,
    session: DB,
    request: Request,
    ai_client: AiClient,
    question_client: QuestionClient,
) -> ScheduleAiCreated:
    # Forward the caller's bearer token so ai/question apply their own org
    # scoping and role checks (already validated on this request) — see
    # docs/design-mode2-scheduling.md.
    authorization = request.headers["authorization"]
    exam = await ai_scheduling_service.schedule_ai_exam(
        session,
        org_id=ctx.org_id,
        ai_client=ai_client,
        question_client=question_client,
        authorization=authorization,
        candidate_email=body.candidate_email,
        candidate_profile_id=body.candidate_profile_id,
        target_role=body.target_role,
        seniority_band=body.seniority_band,
        language_targets=body.language_targets,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    return ScheduleAiCreated(id=exam.id, status=exam.status)


@router.get("", response_model=list[ExamResponse])
async def list_exams(ctx: ReaderCtx, session: DB) -> list[ExamResponse]:
    exams = await scheduling_service.list_exams(session, org_id=ctx.org_id)
    return [ExamResponse.model_validate(e) for e in exams]


@router.get("/{exam_id}", response_model=ExamScheduleResponse)
async def get_exam(
    exam_id: uuid.UUID,
    ctx: ReaderCtx,
    session: DB,
    request: Request,
    redis: RedisDep,
    email_sender: EmailDep,
    ai_client: AiClient,
) -> ExamScheduleResponse:
    exam, invite = await scheduling_service.get_exam_with_invite(
        session, org_id=ctx.org_id, exam_id=exam_id
    )
    authorization = request.headers["authorization"]
    exam = await ai_scheduling_service.refresh_ai_exam(
        session,
        exam,
        org_id=ctx.org_id,
        ai_client=ai_client,
        redis=redis,
        email_sender=email_sender,
        authorization=authorization,
    )
    return ExamScheduleResponse(
        **await _exam_response_kwargs(session, ctx.org_id, exam),
        invite=InviteSummary.model_validate(invite) if invite else None,
        invite_link=None,
    )


@router.post("/{exam_id}/confirm", response_model=ExamResponse)
async def confirm_exam(
    exam_id: uuid.UUID,
    ctx: WriterCtx,
    session: DB,
    request: Request,
    redis: RedisDep,
    email_sender: EmailDep,
    ai_client: AiClient,
) -> ExamResponse:
    exam = await exams_repo.get_by_id(session, org_id=ctx.org_id, exam_id=exam_id)
    if exam is None:
        raise NotFound("Exam not found")
    authorization = request.headers["authorization"]
    exam = await ai_scheduling_service.refresh_ai_exam(
        session,
        exam,
        org_id=ctx.org_id,
        ai_client=ai_client,
        redis=redis,
        email_sender=email_sender,
        authorization=authorization,
    )
    # refresh_ai_exam may have already auto-confirmed (review deadline
    # passed) within the call above — idempotent from the caller's
    # perspective, so only confirm explicitly if that didn't happen.
    if exam.status != ExamStatus.SCHEDULED:
        exam = await ai_scheduling_service.confirm_exam(
            session, exam, org_id=ctx.org_id, redis=redis, email_sender=email_sender
        )
    return ExamResponse(**await _exam_response_kwargs(session, ctx.org_id, exam))


@router.patch("/{exam_id}/slots/{ordinal}/regenerate", response_model=SlotResponse)
async def regenerate_slot(
    exam_id: uuid.UUID,
    ordinal: int,
    ctx: WriterCtx,
    session: DB,
    request: Request,
    redis: RedisDep,
    email_sender: EmailDep,
    ai_client: AiClient,
) -> SlotResponse:
    exam = await exams_repo.get_by_id(session, org_id=ctx.org_id, exam_id=exam_id)
    if exam is None:
        raise NotFound("Exam not found")
    authorization = request.headers["authorization"]
    exam = await ai_scheduling_service.refresh_ai_exam(
        session,
        exam,
        org_id=ctx.org_id,
        ai_client=ai_client,
        redis=redis,
        email_sender=email_sender,
        authorization=authorization,
    )
    slot = await ai_scheduling_service.regenerate_slot(
        session, exam, ordinal, org_id=ctx.org_id, ai_client=ai_client, authorization=authorization
    )
    return SlotResponse.model_validate(slot)
