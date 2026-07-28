import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session_event import SessionEvent


async def create_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    type: str,
    payload: dict[str, Any],
    question_version_id: uuid.UUID | None = None,
) -> SessionEvent:
    # seq assigned inside the same transaction as the insert — a small,
    # accepted race window (single candidate + occasional proctor writes per
    # session; not worth a distributed sequence generator at this volume).
    result = await session.execute(
        select(func.coalesce(func.max(SessionEvent.seq), 0)).where(
            SessionEvent.session_id == session_id
        )
    )
    next_seq = result.scalar_one() + 1
    event = SessionEvent(
        org_id=org_id,
        session_id=session_id,
        seq=next_seq,
        type=type,
        payload=payload,
        question_version_id=question_version_id,
    )
    session.add(event)
    await session.flush()
    return event


async def list_by_session(
    session: AsyncSession, *, org_id: uuid.UUID, session_id: uuid.UUID
) -> Sequence[SessionEvent]:
    result = await session.execute(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id, SessionEvent.org_id == org_id)
        .order_by(SessionEvent.seq)
    )
    return result.scalars().all()
