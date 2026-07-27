"""Background ingestion job, fired via `asyncio.create_task` right after
`POST /profiles` commits — one job per profile, not a persistent queue
consumer (there's no SQS lane for this; see docs/design-profile-ingestion.md).
Tests never start this via asyncio — they call `ingest_profile` directly."""

import logging
import uuid

from app.clients.github import GitHubClient
from app.core.s3 import get_object_bytes
from app.db.session import get_sessionmaker
from app.llm.client import LLMClient
from app.models.candidate_profile import ProfileStatus
from app.pdf.extract import extract_text
from app.repositories import profiles as profiles_repo

logger = logging.getLogger("ai.ingestion")


async def ingest_profile(
    profile_id: uuid.UUID,
    org_id: uuid.UUID,
    *,
    llm_client: LLMClient,
    github_client: GitHubClient,
) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        profile = await profiles_repo.get_by_id(session, org_id=org_id, profile_id=profile_id)
        if profile is None:
            return  # deleted or racing with the request that created it

        try:
            profile.status = ProfileStatus.PROCESSING
            await session.commit()

            pdf_bytes = get_object_bytes(profile.resume_s3_key)
            resume_text = extract_text(pdf_bytes)

            github_signals = None
            if profile.github_handle:
                github_signals = await github_client.fetch_signals(profile.github_handle)

            extracted = await llm_client.extract_profile(resume_text, github_signals)

            profile.years_exp = extracted.years_exp
            profile.domains = extracted.domains
            profile.tech_stack = extracted.tech_stack
            profile.seniority_estimate = extracted.seniority_estimate
            profile.weak_signals = extracted.weak_signals
            profile.strong_signals = extracted.strong_signals
            profile.status = ProfileStatus.READY
            await session.commit()
        except Exception as exc:
            logger.exception("profile ingestion failed for %s", profile_id)
            await session.rollback()
            profile.status = ProfileStatus.FAILED
            profile.error = str(exc)
            await session.commit()
