import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exam import Exam, ExamStatus


async def create_exam(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    blueprint_id: uuid.UUID,
    blueprint_version_id: uuid.UUID,
    candidate_email: str,
    starts_at: datetime,
    ends_at: datetime,
) -> Exam:
    exam = Exam(
        org_id=org_id,
        blueprint_id=blueprint_id,
        blueprint_version_id=blueprint_version_id,
        candidate_email=candidate_email,
        starts_at=starts_at,
        ends_at=ends_at,
        status=ExamStatus.SCHEDULED,
    )
    session.add(exam)
    await session.flush()
    return exam


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, exam_id: uuid.UUID
) -> Exam | None:
    result = await session.execute(
        select(Exam).where(Exam.id == exam_id, Exam.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def list_by_org(session: AsyncSession, *, org_id: uuid.UUID) -> Sequence[Exam]:
    result = await session.execute(
        select(Exam).where(Exam.org_id == org_id).order_by(Exam.created_at)
    )
    return result.scalars().all()
