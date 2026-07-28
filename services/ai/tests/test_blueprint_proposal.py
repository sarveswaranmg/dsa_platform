import uuid

import pytest

from app.core.exceptions import NotFound
from app.db.session import get_sessionmaker
from app.generation.schemas import AvailableTopic
from app.llm.client import MockLLMClient
from app.repositories import profiles as profiles_repo
from app.services import blueprint_proposal as blueprint_proposal_service


async def _seed_profile(org_id: uuid.UUID) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        profile = await profiles_repo.create_profile(
            session, org_id=org_id, resume_s3_key="resumes/x.pdf", github_handle=None
        )
        profile.status = "ready"
        profile.years_exp = 6
        await session.commit()
        return profile.id


async def test_propose_blueprint_returns_a_valid_spec() -> None:
    org_id = uuid.uuid4()
    profile_id = await _seed_profile(org_id)
    topics = [
        AvailableTopic(id=uuid.uuid4(), name="Arrays"),
        AvailableTopic(id=uuid.uuid4(), name="Graphs"),
    ]
    async with get_sessionmaker()() as session:
        spec = await blueprint_proposal_service.propose_blueprint(
            session,
            org_id=org_id,
            candidate_profile_id=profile_id,
            target_role="Backend Engineer",
            seniority_band="senior",
            available_topics=topics,
            llm_client=MockLLMClient(),
        )
    assert sum(slot.weight for slot in spec.topic_mix) == 100
    assert len({slot.topic_id for slot in spec.topic_mix}) == len(spec.topic_mix)
    assert spec.total_duration_minutes > 0
    for slot in spec.topic_mix:
        assert slot.difficulty_min <= slot.difficulty_max


async def test_propose_blueprint_single_topic_gets_full_weight() -> None:
    org_id = uuid.uuid4()
    profile_id = await _seed_profile(org_id)
    topics = [AvailableTopic(id=uuid.uuid4(), name="Arrays")]
    async with get_sessionmaker()() as session:
        spec = await blueprint_proposal_service.propose_blueprint(
            session,
            org_id=org_id,
            candidate_profile_id=profile_id,
            target_role="Backend Engineer",
            seniority_band="senior",
            available_topics=topics,
            llm_client=MockLLMClient(),
        )
    assert len(spec.topic_mix) == 1
    assert spec.topic_mix[0].weight == 100


async def test_propose_blueprint_404s_for_missing_profile() -> None:
    async with get_sessionmaker()() as session:
        with pytest.raises(NotFound):
            await blueprint_proposal_service.propose_blueprint(
                session,
                org_id=uuid.uuid4(),
                candidate_profile_id=uuid.uuid4(),
                target_role="Backend Engineer",
                seniority_band="senior",
                available_topics=[AvailableTopic(id=uuid.uuid4(), name="Arrays")],
                llm_client=MockLLMClient(),
            )


async def test_propose_blueprint_404s_for_other_org_profile() -> None:
    profile_id = await _seed_profile(uuid.uuid4())
    async with get_sessionmaker()() as session:
        with pytest.raises(NotFound):
            await blueprint_proposal_service.propose_blueprint(
                session,
                org_id=uuid.uuid4(),  # different org
                candidate_profile_id=profile_id,
                target_role="Backend Engineer",
                seniority_band="senior",
                available_topics=[AvailableTopic(id=uuid.uuid4(), name="Arrays")],
                llm_client=MockLLMClient(),
            )
