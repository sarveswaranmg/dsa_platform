import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_profile import CandidateProfile, ProfileStatus


async def create_profile(
    session: AsyncSession, *, org_id: uuid.UUID, resume_s3_key: str, github_handle: str | None
) -> CandidateProfile:
    profile = CandidateProfile(
        org_id=org_id,
        resume_s3_key=resume_s3_key,
        github_handle=github_handle,
        status=ProfileStatus.QUEUED,
    )
    session.add(profile)
    await session.flush()
    return profile


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, profile_id: uuid.UUID
) -> CandidateProfile | None:
    result = await session.execute(
        select(CandidateProfile).where(
            CandidateProfile.id == profile_id, CandidateProfile.org_id == org_id
        )
    )
    return result.scalar_one_or_none()
