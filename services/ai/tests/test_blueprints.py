import uuid

from httpx import AsyncClient

from app.db.session import get_sessionmaker
from app.repositories import profiles as profiles_repo


async def _seed_profile(org_id: uuid.UUID) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        profile = await profiles_repo.create_profile(
            session, org_id=org_id, resume_s3_key="resumes/x.pdf", github_handle=None
        )
        profile.status = "ready"
        profile.years_exp = 6
        await session.commit()
        return profile.id


async def test_generate_blueprint_happy_path(
    client: AsyncClient, author: dict[str, str], org_id: uuid.UUID
) -> None:
    profile_id = await _seed_profile(org_id)
    response = await client.post(
        "/blueprints/generate",
        headers=author,
        json={
            "candidate_profile_id": str(profile_id),
            "target_role": "Backend Engineer",
            "seniority_band": "senior",
            "available_topics": [
                {"id": str(uuid.uuid4()), "name": "Arrays"},
                {"id": str(uuid.uuid4()), "name": "Graphs"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert sum(slot["weight"] for slot in body["topic_mix"]) == 100
    assert body["total_duration_minutes"] > 0
    assert body["rationale"]


async def test_generate_blueprint_404s_for_missing_profile(
    client: AsyncClient, author: dict[str, str]
) -> None:
    response = await client.post(
        "/blueprints/generate",
        headers=author,
        json={
            "candidate_profile_id": str(uuid.uuid4()),
            "target_role": "Backend Engineer",
            "seniority_band": "senior",
            "available_topics": [{"id": str(uuid.uuid4()), "name": "Arrays"}],
        },
    )
    assert response.status_code == 404


async def test_reviewer_cannot_generate_blueprint(
    client: AsyncClient, reviewer: dict[str, str], org_id: uuid.UUID
) -> None:
    profile_id = await _seed_profile(org_id)
    response = await client.post(
        "/blueprints/generate",
        headers=reviewer,
        json={
            "candidate_profile_id": str(profile_id),
            "target_role": "Backend Engineer",
            "seniority_band": "senior",
            "available_topics": [{"id": str(uuid.uuid4()), "name": "Arrays"}],
        },
    )
    assert response.status_code == 403


async def test_missing_token_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/blueprints/generate",
        json={
            "candidate_profile_id": str(uuid.uuid4()),
            "target_role": "Backend Engineer",
            "seniority_band": "senior",
            "available_topics": [{"id": str(uuid.uuid4()), "name": "Arrays"}],
        },
    )
    assert response.status_code == 401
