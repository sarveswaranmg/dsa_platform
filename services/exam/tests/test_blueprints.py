import uuid

from httpx import AsyncClient

from tests.conftest import one_topic_blueprint


async def test_create_blueprint_v1(client: AsyncClient, author: dict[str, str]) -> None:
    topic_id = uuid.uuid4()
    response = await client.post(
        "/blueprints", headers=author, json=one_topic_blueprint(topic_id)
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Backend Screen"
    assert body["current_version"]["version_number"] == 1
    assert body["current_version"]["topic_mix"][0]["topic_id"] == str(topic_id)


async def test_weights_must_sum_to_100(client: AsyncClient, author: dict[str, str]) -> None:
    body = one_topic_blueprint(uuid.uuid4())
    body["topic_mix"][0]["weight"] = 60  # type: ignore[index]
    response = await client.post("/blueprints", headers=author, json=body)
    assert response.status_code == 422


async def test_two_entry_weights_sum(client: AsyncClient, author: dict[str, str]) -> None:
    body = {
        "name": "Mixed",
        "target_role": "SWE",
        "experience_band": "mid",
        "total_duration_minutes": 60,
        "topic_mix": [
            {"topic_id": str(uuid.uuid4()), "weight": 50, "difficulty_min": 1,
             "difficulty_max": 2, "question_count": 1},
            {"topic_id": str(uuid.uuid4()), "weight": 50, "difficulty_min": 2,
             "difficulty_max": 3, "question_count": 1},
        ],
    }
    response = await client.post("/blueprints", headers=author, json=body)
    assert response.status_code == 201


async def test_difficulty_range_inverted_rejected(
    client: AsyncClient, author: dict[str, str]
) -> None:
    body = one_topic_blueprint(uuid.uuid4(), difficulty_min=4, difficulty_max=2)
    response = await client.post("/blueprints", headers=author, json=body)
    assert response.status_code == 422


async def test_question_count_must_be_positive(
    client: AsyncClient, author: dict[str, str]
) -> None:
    body = one_topic_blueprint(uuid.uuid4(), question_count=0)
    response = await client.post("/blueprints", headers=author, json=body)
    assert response.status_code == 422


async def test_empty_mix_rejected(client: AsyncClient, author: dict[str, str]) -> None:
    body = one_topic_blueprint(uuid.uuid4())
    body["topic_mix"] = []
    response = await client.post("/blueprints", headers=author, json=body)
    assert response.status_code == 422


async def test_duplicate_topic_rejected(client: AsyncClient, author: dict[str, str]) -> None:
    tid = str(uuid.uuid4())
    body = {
        "name": "Dupe",
        "target_role": "SWE",
        "experience_band": "mid",
        "total_duration_minutes": 60,
        "topic_mix": [
            {"topic_id": tid, "weight": 50, "difficulty_min": 1, "difficulty_max": 2,
             "question_count": 1},
            {"topic_id": tid, "weight": 50, "difficulty_min": 1, "difficulty_max": 2,
             "question_count": 1},
        ],
    }
    response = await client.post("/blueprints", headers=author, json=body)
    assert response.status_code == 422


async def test_patch_creates_immutable_new_version(
    client: AsyncClient, author: dict[str, str]
) -> None:
    topic_id = uuid.uuid4()
    created = (
        await client.post("/blueprints", headers=author, json=one_topic_blueprint(topic_id))
    ).json()
    bid = created["id"]
    v1_id = created["current_version"]["id"]

    updated = one_topic_blueprint(topic_id, question_count=5, name="Backend Screen v2")
    patched = await client.patch(f"/blueprints/{bid}", headers=author, json=updated)
    assert patched.status_code == 200
    body = patched.json()
    assert body["current_version"]["version_number"] == 2
    assert body["current_version"]["topic_mix"][0]["question_count"] == 5
    assert body["name"] == "Backend Screen v2"

    # v1 is untouched.
    versions = (await client.get(f"/blueprints/{bid}/versions", headers=author)).json()
    assert [v["version_number"] for v in versions] == [1, 2]
    v1 = next(v for v in versions if v["version_number"] == 1)
    assert v1["id"] == v1_id
    assert v1["topic_mix"][0]["question_count"] == 2


async def test_list_blueprints_scoped_to_org(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    await client.post("/blueprints", headers=author, json=one_topic_blueprint(uuid.uuid4()))
    mine = (await client.get("/blueprints", headers=author)).json()
    assert len(mine) == 1
    theirs = (await client.get("/blueprints", headers=other_org_author)).json()
    assert theirs == []


async def test_cross_org_get_and_patch_denied(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    topic_id = uuid.uuid4()
    created = (
        await client.post("/blueprints", headers=author, json=one_topic_blueprint(topic_id))
    ).json()
    bid = created["id"]
    assert (await client.get(f"/blueprints/{bid}", headers=other_org_author)).status_code == 404
    patch = await client.patch(
        f"/blueprints/{bid}", headers=other_org_author, json=one_topic_blueprint(topic_id)
    )
    assert patch.status_code == 404


async def test_reviewer_cannot_write(client: AsyncClient, reviewer: dict[str, str]) -> None:
    response = await client.post(
        "/blueprints", headers=reviewer, json=one_topic_blueprint(uuid.uuid4())
    )
    assert response.status_code == 403


async def test_missing_token_rejected(client: AsyncClient) -> None:
    assert (await client.get("/blueprints")).status_code == 401
