import uuid

from httpx import AsyncClient

from tests.conftest import create_question_api


async def test_internal_lists_version_test_cases(
    client: AsyncClient, author: dict[str, str], org_id: uuid.UUID
) -> None:
    question = await create_question_api(client, author)
    version_id = question["current_version"]["id"]
    created = await client.post(
        f"/questions/{question['id']}/test-cases", headers=author, json={"is_sample": True}
    )
    assert created.status_code == 201

    response = await client.get(
        f"/internal/question-versions/{version_id}/test-cases", params={"org_id": str(org_id)}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ordinal"] == 1
    assert body[0]["input_s3_key"] and body[0]["expected_output_s3_key"]


async def test_internal_scoped_by_org(
    client: AsyncClient, author: dict[str, str]
) -> None:
    question = await create_question_api(client, author)
    version_id = question["current_version"]["id"]
    await client.post(f"/questions/{question['id']}/test-cases", headers=author, json={})

    # A different org sees no test cases for that version.
    response = await client.get(
        f"/internal/question-versions/{version_id}/test-cases",
        params={"org_id": str(uuid.uuid4())},
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_internal_published_questions_and_content(
    client: AsyncClient, author: dict[str, str], org_id: uuid.UUID
) -> None:
    topic = (await client.post("/topics", headers=author, json={"name": "arrays"})).json()
    q = await create_question_api(
        client, author, difficulty=3, topic_ids=[topic["id"]]
    )
    # Draft questions are invisible; only published ones appear.
    empty = await client.get(
        "/internal/published-questions",
        params={"org_id": str(org_id), "topic_id": topic["id"], "difficulty": 3},
    )
    assert empty.json() == []

    await client.post(f"/questions/{q['id']}/publish", headers=author)
    listed = await client.get(
        "/internal/published-questions",
        params={"org_id": str(org_id), "topic_id": topic["id"], "difficulty": 3},
    )
    body = listed.json()
    assert len(body) == 1
    assert body[0]["question_id"] == q["id"]
    version_id = body[0]["published_version_id"]

    content = await client.get(
        f"/internal/question-versions/{version_id}", params={"org_id": str(org_id)}
    )
    assert content.status_code == 200
    assert content.json()["title"] == q["current_version"]["title"]
    assert content.json()["difficulty"] == 3


async def test_internal_version_content_not_found(
    client: AsyncClient, org_id: uuid.UUID
) -> None:
    response = await client.get(
        f"/internal/question-versions/{uuid.uuid4()}", params={"org_id": str(org_id)}
    )
    assert response.status_code == 404
