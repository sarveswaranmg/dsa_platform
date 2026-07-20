import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_role
from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.session import get_db
from app.models.examiner import Role
from app.notifications.email import EmailSender, get_email_sender
from app.schemas.exam import (
    ExamResponse,
    ExamScheduleRequest,
    ExamScheduleResponse,
    InviteSummary,
)
from app.services import scheduling as scheduling_service

router = APIRouter(prefix="/exams", tags=["exams"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
ReaderCtx = Annotated[AuthContext, Depends(require_role())]
RedisDep = Annotated[Redis, Depends(get_redis)]
EmailDep = Annotated[EmailSender, Depends(get_email_sender)]


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
        **ExamResponse.model_validate(exam).model_dump(),
        invite=InviteSummary.model_validate(invite),
        invite_link=link if show_link else None,
    )


@router.get("", response_model=list[ExamResponse])
async def list_exams(ctx: ReaderCtx, session: DB) -> list[ExamResponse]:
    exams = await scheduling_service.list_exams(session, org_id=ctx.org_id)
    return [ExamResponse.model_validate(e) for e in exams]


@router.get("/{exam_id}", response_model=ExamScheduleResponse)
async def get_exam(
    exam_id: uuid.UUID, ctx: ReaderCtx, session: DB
) -> ExamScheduleResponse:
    exam, invite = await scheduling_service.get_exam_with_invite(
        session, org_id=ctx.org_id, exam_id=exam_id
    )
    return ExamScheduleResponse(
        **ExamResponse.model_validate(exam).model_dump(),
        invite=InviteSummary.model_validate(invite) if invite else None,
        invite_link=None,
    )
