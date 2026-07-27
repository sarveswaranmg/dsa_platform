import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.github import GitHubClient
from app.core import s3
from app.core.exceptions import NotFound
from app.llm.client import LLMClient
from app.models.candidate_profile import CandidateProfile
from app.repositories import profiles as profiles_repo
from app.services.ingestion import ingest_profile

# asyncio only holds a weak reference to a task's coroutine — without keeping
# a strong reference here, a fire-and-forget task can be garbage-collected
# mid-run. Cleared via the task's own done callback.
_background_tasks: set[asyncio.Task[None]] = set()


def create_upload_url() -> tuple[str, str]:
    key = f"resumes/{uuid.uuid4()}.pdf"
    return key, s3.presign_put(key)


async def create_profile(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    resume_s3_key: str,
    github_handle: str | None,
    llm_client: LLMClient,
    github_client: GitHubClient,
) -> CandidateProfile:
    profile = await profiles_repo.create_profile(
        session, org_id=org_id, resume_s3_key=resume_s3_key, github_handle=github_handle
    )
    await session.commit()

    task = asyncio.create_task(
        ingest_profile(
            profile.id, org_id, llm_client=llm_client, github_client=github_client
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return profile


async def get_profile(
    session: AsyncSession, *, org_id: uuid.UUID, profile_id: uuid.UUID
) -> CandidateProfile:
    profile = await profiles_repo.get_by_id(session, org_id=org_id, profile_id=profile_id)
    if profile is None:
        raise NotFound("Profile not found")
    return profile
