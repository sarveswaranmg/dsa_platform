import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_job import GenerationJob, GenerationStatus


async def create_job(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    topic_id: uuid.UUID,
    difficulty_band: str,
    language_targets: list[str],
) -> GenerationJob:
    job = GenerationJob(
        org_id=org_id,
        topic_id=topic_id,
        difficulty_band=difficulty_band,
        language_targets=language_targets,
        status=GenerationStatus.QUEUED,
    )
    session.add(job)
    await session.flush()
    return job


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, job_id: uuid.UUID
) -> GenerationJob | None:
    result = await session.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id, GenerationJob.org_id == org_id
        )
    )
    return result.scalar_one_or_none()


async def get_succeeded_by_version(
    session: AsyncSession, *, org_id: uuid.UUID, question_version_id: uuid.UUID
) -> GenerationJob | None:
    """The test-case factory's source of reference/brute-force solutions and
    the draft's input_spec (Phase 2 Slice 3) — only succeeded generation
    jobs have both."""
    result = await session.execute(
        select(GenerationJob).where(
            GenerationJob.question_version_id == question_version_id,
            GenerationJob.org_id == org_id,
            GenerationJob.status == GenerationStatus.SUCCEEDED,
        )
    )
    return result.scalar_one_or_none()
