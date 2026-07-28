import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_case_generation_job import TestCaseGenerationJob, TestCaseGenerationStatus


async def create_job(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    question_id: uuid.UUID,
    question_version_id: uuid.UUID,
    generation_job_id: uuid.UUID,
    synchronous: bool,
) -> TestCaseGenerationJob:
    job = TestCaseGenerationJob(
        org_id=org_id,
        question_id=question_id,
        question_version_id=question_version_id,
        generation_job_id=generation_job_id,
        synchronous=synchronous,
        status=TestCaseGenerationStatus.QUEUED,
    )
    session.add(job)
    await session.flush()
    return job


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, job_id: uuid.UUID
) -> TestCaseGenerationJob | None:
    result = await session.execute(
        select(TestCaseGenerationJob).where(
            TestCaseGenerationJob.id == job_id, TestCaseGenerationJob.org_id == org_id
        )
    )
    return result.scalar_one_or_none()
