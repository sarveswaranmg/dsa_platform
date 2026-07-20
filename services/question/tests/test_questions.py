from httpx import AsyncClient

from tests.conftest import QUESTION_DEFAULTS, create_question_api


async def test_create_question_draft_v1(client: AsyncClient, author: dict[str, str]) -> None:
    data = await create_question_api(client, author)
    assert data["status"] == "draft"
    assert data["published_version_id"] is None
    assert data["current_version"]["version_number"] == 1
    assert data["current_version"]["starter_code"] == QUESTION_DEFAULTS["starter_code"]


async def test_patch_draft_mutates_in_place(
    client: AsyncClient, author: dict[str, str]
) -> None:
    data = await create_question_api(client, author)
    response = await client.patch(
        f"/questions/{data['id']}", headers=author, json={"title": "Two Sum II"}
    )
    assert response.status_code == 200
    assert response.json()["current_version"]["version_number"] == 1
    versions = await client.get(f"/questions/{data['id']}/versions", headers=author)
    assert len(versions.json()) == 1


async def test_publish_then_edit_creates_immutable_new_version(
    client: AsyncClient, author: dict[str, str]
) -> None:
    data = await create_question_api(client, author)
    qid = data["id"]

    published = await client.post(f"/questions/{qid}/publish", headers=author)
    assert published.status_code == 200
    v1_id = published.json()["published_version_id"]
    assert v1_id == published.json()["current_version"]["id"]

    # Edit after publish → copy-on-write v2; published pointer still v1.
    patched = await client.patch(
        f"/questions/{qid}", headers=author, json={"title": "Harder Two Sum", "difficulty": 4}
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["current_version"]["version_number"] == 2
    assert body["current_version"]["title"] == "Harder Two Sum"
    assert body["published_version_id"] == v1_id

    # v1 is untouched — the immutability guarantee grading relies on.
    versions = (await client.get(f"/questions/{qid}/versions", headers=author)).json()
    v1 = next(v for v in versions if v["version_number"] == 1)
    assert v1["id"] == v1_id
    assert v1["title"] == QUESTION_DEFAULTS["title"]
    assert v1["difficulty"] == QUESTION_DEFAULTS["difficulty"]

    # Publishing again moves the pointer to v2.
    republished = await client.post(f"/questions/{qid}/publish", headers=author)
    assert republished.json()["published_version_id"] == body["current_version"]["id"]


async def test_publish_already_published_conflict(
    client: AsyncClient, author: dict[str, str]
) -> None:
    data = await create_question_api(client, author)
    await client.post(f"/questions/{data['id']}/publish", headers=author)
    response = await client.post(f"/questions/{data['id']}/publish", headers=author)
    assert response.status_code == 409


async def test_list_filters(client: AsyncClient, author: dict[str, str]) -> None:
    topic = (
        await client.post("/topics", headers=author, json={"name": "arrays"})
    ).json()
    easy = await create_question_api(
        client, author, title="Easy", difficulty=1, topic_ids=[topic["id"]]
    )
    await create_question_api(client, author, title="Hard", difficulty=5)

    by_topic = (
        await client.get(f"/questions?topic_id={topic['id']}", headers=author)
    ).json()
    assert [q["id"] for q in by_topic] == [easy["id"]]

    by_difficulty = (await client.get("/questions?difficulty=5", headers=author)).json()
    assert [q["title"] for q in by_difficulty] == ["Hard"]

    published = (await client.get("/questions?status=published", headers=author)).json()
    assert published == []


async def test_difficulty_bounds_rejected(
    client: AsyncClient, author: dict[str, str]
) -> None:
    response = await client.post(
        "/questions", headers=author, json={**QUESTION_DEFAULTS, "difficulty": 6}
    )
    assert response.status_code == 422


async def test_unknown_starter_language_rejected(
    client: AsyncClient, author: dict[str, str]
) -> None:
    response = await client.post(
        "/questions",
        headers=author,
        json={**QUESTION_DEFAULTS, "starter_code": {"rust": "fn main() {}"}},
    )
    assert response.status_code == 422


async def test_cross_org_question_invisible(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    data = await create_question_api(client, author)
    response = await client.get(f"/questions/{data['id']}", headers=other_org_author)
    assert response.status_code == 404


async def test_reviewer_cannot_write_questions(
    client: AsyncClient, reviewer: dict[str, str]
) -> None:
    response = await client.post(
        "/questions", headers=reviewer, json=dict(QUESTION_DEFAULTS)
    )
    assert response.status_code == 403
