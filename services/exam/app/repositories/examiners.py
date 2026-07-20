import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.examiner import Examiner, Role


async def create_examiner(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    email: str,
    password_hash: str,
    role: Role,
    totp_secret: str,
) -> Examiner:
    examiner = Examiner(
        org_id=org_id,
        email=email,
        password_hash=password_hash,
        role=role,
        totp_secret=totp_secret,
    )
    session.add(examiner)
    await session.flush()
    return examiner


async def get_by_email(session: AsyncSession, email: str) -> Examiner | None:
    # Auth-plane lookup: intentionally unscoped — login carries no org context.
    result = await session.execute(select(Examiner).where(Examiner.email == email))
    return result.scalar_one_or_none()


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, examiner_id: uuid.UUID
) -> Examiner | None:
    result = await session.execute(
        select(Examiner).where(Examiner.id == examiner_id, Examiner.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def list_by_org(session: AsyncSession, *, org_id: uuid.UUID) -> Sequence[Examiner]:
    result = await session.execute(
        select(Examiner).where(Examiner.org_id == org_id).order_by(Examiner.created_at)
    )
    return result.scalars().all()
