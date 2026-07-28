import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exam_slot_question import ExamSlotQuestion, SlotStatus


async def create_slot(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    exam_id: uuid.UUID,
    ordinal: int,
    topic_id: uuid.UUID,
    difficulty_band: str,
    generation_job_id: uuid.UUID,
) -> ExamSlotQuestion:
    slot = ExamSlotQuestion(
        org_id=org_id,
        exam_id=exam_id,
        ordinal=ordinal,
        topic_id=topic_id,
        difficulty_band=difficulty_band,
        generation_job_id=generation_job_id,
        status=SlotStatus.PENDING.value,
    )
    session.add(slot)
    await session.flush()
    return slot


async def list_by_exam(
    session: AsyncSession, *, org_id: uuid.UUID, exam_id: uuid.UUID
) -> Sequence[ExamSlotQuestion]:
    result = await session.execute(
        select(ExamSlotQuestion)
        .where(ExamSlotQuestion.org_id == org_id, ExamSlotQuestion.exam_id == exam_id)
        .order_by(ExamSlotQuestion.ordinal)
    )
    return result.scalars().all()


async def get_by_ordinal(
    session: AsyncSession, *, org_id: uuid.UUID, exam_id: uuid.UUID, ordinal: int
) -> ExamSlotQuestion | None:
    result = await session.execute(
        select(ExamSlotQuestion).where(
            ExamSlotQuestion.org_id == org_id,
            ExamSlotQuestion.exam_id == exam_id,
            ExamSlotQuestion.ordinal == ordinal,
        )
    )
    return result.scalar_one_or_none()
