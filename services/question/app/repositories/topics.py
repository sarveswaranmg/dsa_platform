import uuid
from collections.abc import Sequence

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import question_topics
from app.models.topic import Topic


async def create_topic(
    session: AsyncSession, *, org_id: uuid.UUID, name: str, parent_id: uuid.UUID | None
) -> Topic:
    topic = Topic(org_id=org_id, name=name, parent_id=parent_id)
    session.add(topic)
    await session.flush()
    return topic


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, topic_id: uuid.UUID
) -> Topic | None:
    result = await session.execute(
        select(Topic).where(Topic.id == topic_id, Topic.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def get_many(
    session: AsyncSession, *, org_id: uuid.UUID, topic_ids: Sequence[uuid.UUID]
) -> Sequence[Topic]:
    if not topic_ids:
        return []
    result = await session.execute(
        select(Topic).where(Topic.id.in_(topic_ids), Topic.org_id == org_id)
    )
    return result.scalars().all()


async def list_by_org(session: AsyncSession, *, org_id: uuid.UUID) -> Sequence[Topic]:
    result = await session.execute(
        select(Topic).where(Topic.org_id == org_id).order_by(Topic.created_at)
    )
    return result.scalars().all()


async def has_children(
    session: AsyncSession, *, org_id: uuid.UUID, topic_id: uuid.UUID
) -> bool:
    result = await session.execute(
        select(exists().where(Topic.parent_id == topic_id, Topic.org_id == org_id))
    )
    return bool(result.scalar())


async def is_linked_to_questions(session: AsyncSession, *, topic_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(exists().where(question_topics.c.topic_id == topic_id))
    )
    return bool(result.scalar())


async def delete_topic(session: AsyncSession, topic: Topic) -> None:
    await session.delete(topic)
    await session.flush()
