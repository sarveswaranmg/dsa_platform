import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, Role, require_role
from app.db.session import get_db
from app.models.question import Question, QuestionStatus
from app.models.question_version import QuestionVersion
from app.schemas.question import (
    QuestionCreate,
    QuestionListItem,
    QuestionResponse,
    QuestionUpdate,
    QuestionVersionResponse,
)
from app.services import questions as questions_service

router = APIRouter(prefix="/questions", tags=["questions"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
ReaderCtx = Annotated[AuthContext, Depends(require_role())]


def _detail(
    question: Question, version: QuestionVersion, topic_ids: list[uuid.UUID]
) -> QuestionResponse:
    return QuestionResponse(
        id=question.id,
        org_id=question.org_id,
        status=question.status,
        published_version_id=question.published_version_id,
        current_version=QuestionVersionResponse.model_validate(version),
        topic_ids=topic_ids,
    )


@router.post("", response_model=QuestionResponse, status_code=201)
async def create_question(
    body: QuestionCreate, ctx: WriterCtx, session: DB
) -> QuestionResponse:
    question, version, topic_ids = await questions_service.create_question(
        session,
        org_id=ctx.org_id,
        title=body.title,
        statement_md=body.statement_md,
        constraints_md=body.constraints_md,
        difficulty=body.difficulty,
        time_limit_ms=body.time_limit_ms,
        memory_limit_mb=body.memory_limit_mb,
        starter_code={k.value: v for k, v in body.starter_code.items()},
        topic_ids=body.topic_ids,
    )
    return _detail(question, version, topic_ids)


@router.get("", response_model=list[QuestionListItem])
async def list_questions(
    ctx: ReaderCtx,
    session: DB,
    topic_id: uuid.UUID | None = None,
    difficulty: Annotated[int | None, "1-5"] = None,
    status: QuestionStatus | None = None,
) -> list[QuestionListItem]:
    rows = await questions_service.list_questions(
        session, org_id=ctx.org_id, topic_id=topic_id, difficulty=difficulty, status=status
    )
    return [
        QuestionListItem(
            id=q.id,
            status=q.status,
            title=v.title,
            difficulty=v.difficulty,
            version_number=v.version_number,
        )
        for q, v in rows
    ]


@router.get("/{question_id}", response_model=QuestionResponse)
async def get_question(
    question_id: uuid.UUID, ctx: ReaderCtx, session: DB
) -> QuestionResponse:
    question, version, topic_ids = await questions_service.get_question_detail(
        session, org_id=ctx.org_id, question_id=question_id
    )
    return _detail(question, version, topic_ids)


@router.patch("/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: uuid.UUID, body: QuestionUpdate, ctx: WriterCtx, session: DB
) -> QuestionResponse:
    fields = body.model_dump(exclude_unset=True, exclude={"topic_ids"})
    if "starter_code" in fields and body.starter_code is not None:
        fields["starter_code"] = {k.value: v for k, v in body.starter_code.items()}
    question, version, topic_ids = await questions_service.update_question(
        session,
        org_id=ctx.org_id,
        question_id=question_id,
        version_fields=fields,
        topic_ids=body.topic_ids if "topic_ids" in body.model_fields_set else None,
    )
    return _detail(question, version, topic_ids)


@router.post("/{question_id}/publish", response_model=QuestionResponse)
async def publish_question(
    question_id: uuid.UUID, ctx: WriterCtx, session: DB
) -> QuestionResponse:
    question, version, topic_ids = await questions_service.publish_question(
        session, org_id=ctx.org_id, question_id=question_id
    )
    return _detail(question, version, topic_ids)


@router.get("/{question_id}/versions", response_model=list[QuestionVersionResponse])
async def list_versions(
    question_id: uuid.UUID, ctx: ReaderCtx, session: DB
) -> list[QuestionVersionResponse]:
    versions = await questions_service.list_versions(
        session, org_id=ctx.org_id, question_id=question_id
    )
    return [QuestionVersionResponse.model_validate(v) for v in versions]
