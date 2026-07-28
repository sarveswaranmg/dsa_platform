"""Event-sourcing spine for a candidate session (Phase 2 Slice 6). Every
meaningful thing that happens in a session is written as an append-only
`SessionEvent` row and published to a Redis pub/sub channel so any live
WebSocket connection (candidate, proctor) sees it immediately without
polling the DB. See docs/design-live-proctoring.md."""

import json
import uuid
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_keys import session_events_channel
from app.models.session_event import SessionEvent
from app.repositories import session_events as session_events_repo


async def emit(
    session: AsyncSession,
    redis: Redis,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    type: str,
    payload: dict[str, Any],
    question_version_id: uuid.UUID | None = None,
) -> SessionEvent:
    event = await session_events_repo.create_event(
        session,
        org_id=org_id,
        session_id=session_id,
        type=type,
        payload=payload,
        question_version_id=question_version_id,
    )
    await session.commit()
    await redis.publish(
        session_events_channel(session_id),
        json.dumps(
            {
                "seq": event.seq,
                "type": event.type,
                "payload": event.payload,
                "question_version_id": (
                    str(event.question_version_id) if event.question_version_id else None
                ),
            }
        ),
    )
    return event
