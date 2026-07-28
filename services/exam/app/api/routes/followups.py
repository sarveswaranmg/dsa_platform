"""Mid-exam proctor follow-ups + session replay (Phase 2 Slice 6). See
docs/design-live-proctoring.md."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_role
from app.clients.ai_service import AiServiceClient, get_ai_client
from app.clients.question_service import QuestionServiceClient, get_question_client
from app.core.redis import get_redis
from app.db.session import get_db
from app.models.examiner import Role
from app.repositories import session_events as session_events_repo
from app.schemas.followup import FollowupRequest, FollowupResponse, SessionEventResponse
from app.services import followups as followups_service

router = APIRouter(prefix="/sessions", tags=["followups"])

DB = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
ProctorCtx = Annotated[AuthContext, Depends(require_role(Role.PROCTOR))]
ReviewerCtx = Annotated[AuthContext, Depends(require_role(Role.REVIEWER))]
AiClient = Annotated[AiServiceClient, Depends(get_ai_client)]
QuestionClient = Annotated[QuestionServiceClient, Depends(get_question_client)]


@router.post("/{session_id}/followup", response_model=FollowupResponse)
async def push_followup(
    session_id: uuid.UUID,
    body: FollowupRequest,
    ctx: ProctorCtx,
    session: DB,
    redis: RedisDep,
    question_client: QuestionClient,
    ai_client: AiClient,
) -> FollowupResponse:
    event = await followups_service.push_followup(
        session,
        redis,
        question_client,
        ai_client,
        org_id=ctx.org_id,
        session_id=session_id,
        ordinal=body.ordinal,
        modified_constraints_md=body.modified_constraints_md,
    )
    return FollowupResponse(
        previous_version_id=uuid.UUID(event.payload["previous_version_id"]),
        new_version_id=uuid.UUID(event.payload["new_version_id"]),
    )


@router.get("/{session_id}/replay", response_model=list[SessionEventResponse])
async def replay_session(
    session_id: uuid.UUID, ctx: ReviewerCtx, session: DB
) -> list[SessionEventResponse]:
    events = await session_events_repo.list_by_session(
        session, org_id=ctx.org_id, session_id=session_id
    )
    return [
        SessionEventResponse(
            seq=e.seq,
            type=e.type,
            payload=e.payload,
            question_version_id=e.question_version_id,
            created_at=e.created_at,
        )
        for e in events
    ]
