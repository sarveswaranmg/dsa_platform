"""Phase 2 Slice 4: propose a Mode 2 exam blueprint for a candidate profile.
Synchronous — one LLM call, no judge involvement, nothing stored (ai doesn't
own blueprints; `exam` creates the actual blueprint from this proposal)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.generation.schemas import AvailableTopic, BlueprintSpec
from app.llm.client import LLMClient
from app.repositories import profiles as profiles_repo


async def propose_blueprint(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    candidate_profile_id: uuid.UUID,
    target_role: str,
    seniority_band: str,
    available_topics: list[AvailableTopic],
    llm_client: LLMClient,
) -> BlueprintSpec:
    profile = await profiles_repo.get_by_id(
        session, org_id=org_id, profile_id=candidate_profile_id
    )
    if profile is None:
        raise NotFound("Candidate profile not found")
    return await llm_client.propose_blueprint(
        profile,
        target_role=target_role,
        seniority_band=seniority_band,
        available_topics=available_topics,
    )
