import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound
from app.models.topic import Topic
from app.repositories import topics as topics_repo


async def _require_topic(
    session: AsyncSession, *, org_id: uuid.UUID, topic_id: uuid.UUID
) -> Topic:
    topic = await topics_repo.get_by_id(session, org_id=org_id, topic_id=topic_id)
    if topic is None:
        raise NotFound("Topic not found")
    return topic


async def _reject_cycle(
    session: AsyncSession, *, org_id: uuid.UUID, topic_id: uuid.UUID, new_parent_id: uuid.UUID
) -> None:
    """Walk up from the proposed parent; hitting `topic_id` means a cycle."""
    cursor: uuid.UUID | None = new_parent_id
    while cursor is not None:
        if cursor == topic_id:
            raise Conflict("Topic parent would create a cycle")
        parent = await _require_topic(session, org_id=org_id, topic_id=cursor)
        cursor = parent.parent_id


async def create_topic(
    session: AsyncSession, *, org_id: uuid.UUID, name: str, parent_id: uuid.UUID | None
) -> Topic:
    if parent_id is not None:
        await _require_topic(session, org_id=org_id, topic_id=parent_id)
    topic = await topics_repo.create_topic(
        session, org_id=org_id, name=name, parent_id=parent_id
    )
    await session.commit()
    return topic


async def list_topics(session: AsyncSession, *, org_id: uuid.UUID) -> Sequence[Topic]:
    return await topics_repo.list_by_org(session, org_id=org_id)


async def update_topic(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    topic_id: uuid.UUID,
    name: str | None,
    parent_id: uuid.UUID | None,
    parent_set: bool,
) -> Topic:
    topic = await _require_topic(session, org_id=org_id, topic_id=topic_id)
    if name is not None:
        topic.name = name
    if parent_set:
        if parent_id is not None:
            await _reject_cycle(
                session, org_id=org_id, topic_id=topic_id, new_parent_id=parent_id
            )
        topic.parent_id = parent_id
    await session.commit()
    return topic


async def delete_topic(
    session: AsyncSession, *, org_id: uuid.UUID, topic_id: uuid.UUID
) -> None:
    topic = await _require_topic(session, org_id=org_id, topic_id=topic_id)
    if await topics_repo.has_children(session, org_id=org_id, topic_id=topic_id):
        raise Conflict("Topic has child topics")
    if await topics_repo.is_linked_to_questions(session, topic_id=topic_id):
        raise Conflict("Topic is attached to questions")
    await topics_repo.delete_topic(session, topic)
    await session.commit()
