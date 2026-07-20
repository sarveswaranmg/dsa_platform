import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invite import Invite


async def create_invite(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    exam_id: uuid.UUID,
    jti: str,
    candidate_email: str,
) -> Invite:
    invite = Invite(
        org_id=org_id, exam_id=exam_id, jti=jti, candidate_email=candidate_email
    )
    session.add(invite)
    await session.flush()
    return invite


async def get_by_id(
    session: AsyncSession, *, invite_id: uuid.UUID
) -> Invite | None:
    result = await session.execute(select(Invite).where(Invite.id == invite_id))
    return result.scalar_one_or_none()


async def get_for_exam(
    session: AsyncSession, *, org_id: uuid.UUID, exam_id: uuid.UUID
) -> Invite | None:
    result = await session.execute(
        select(Invite).where(Invite.exam_id == exam_id, Invite.org_id == org_id)
    )
    return result.scalar_one_or_none()
