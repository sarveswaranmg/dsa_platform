import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, Role, require_role
from app.db.session import get_db
from app.schemas.topic import TopicCreate, TopicResponse, TopicUpdate
from app.services import topics as topics_service

router = APIRouter(prefix="/topics", tags=["topics"])

DB = Annotated[AsyncSession, Depends(get_db)]
WriterCtx = Annotated[AuthContext, Depends(require_role(Role.ADMIN, Role.AUTHOR))]
ReaderCtx = Annotated[AuthContext, Depends(require_role())]


@router.post("", response_model=TopicResponse, status_code=201)
async def create_topic(body: TopicCreate, ctx: WriterCtx, session: DB) -> TopicResponse:
    topic = await topics_service.create_topic(
        session, org_id=ctx.org_id, name=body.name, parent_id=body.parent_id
    )
    return TopicResponse.model_validate(topic)


@router.get("", response_model=list[TopicResponse])
async def list_topics(ctx: ReaderCtx, session: DB) -> list[TopicResponse]:
    topics = await topics_service.list_topics(session, org_id=ctx.org_id)
    return [TopicResponse.model_validate(t) for t in topics]


@router.patch("/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: uuid.UUID, body: TopicUpdate, ctx: WriterCtx, session: DB
) -> TopicResponse:
    topic = await topics_service.update_topic(
        session,
        org_id=ctx.org_id,
        topic_id=topic_id,
        name=body.name,
        parent_id=body.parent_id,
        parent_set="parent_id" in body.model_fields_set,
    )
    return TopicResponse.model_validate(topic)


@router.delete("/{topic_id}", status_code=204)
async def delete_topic(topic_id: uuid.UUID, ctx: WriterCtx, session: DB) -> None:
    await topics_service.delete_topic(session, org_id=ctx.org_id, topic_id=topic_id)
