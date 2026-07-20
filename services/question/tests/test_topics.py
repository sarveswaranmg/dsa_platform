from httpx import AsyncClient

from tests.conftest import create_question_api


async def _create_topic(
    client: AsyncClient, headers: dict[str, str], name: str, parent_id: str | None = None
) -> dict[str, str]:
    response = await client.post(
        "/topics", headers=headers, json={"name": name, "parent_id": parent_id}
    )
    assert response.status_code == 201, response.text
    data: dict[str, str] = response.json()
    return data


async def test_create_and_list_nested_topics(
    client: AsyncClient, author: dict[str, str]
) -> None:
    arrays = await _create_topic(client, author, "arrays")
    two_pointers = await _create_topic(client, author, "two-pointers", arrays["id"])
    await _create_topic(client, author, "sliding-window", two_pointers["id"])

    response = await client.get("/topics", headers=author)
    assert response.status_code == 200
    topics = response.json()
    by_name = {t["name"]: t for t in topics}
    assert by_name["two-pointers"]["parent_id"] == arrays["id"]
    assert by_name["sliding-window"]["parent_id"] == two_pointers["id"]


async def test_parent_must_exist_in_same_org(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    foreign = await _create_topic(client, other_org_author, "their-topic")
    response = await client.post(
        "/topics", headers=author, json={"name": "mine", "parent_id": foreign["id"]}
    )
    assert response.status_code == 404


async def test_cycle_rejected(client: AsyncClient, author: dict[str, str]) -> None:
    a = await _create_topic(client, author, "a")
    b = await _create_topic(client, author, "b", a["id"])
    c = await _create_topic(client, author, "c", b["id"])
    # a -> c would close the loop a -> b -> c -> a.
    response = await client.patch(
        f"/topics/{a['id']}", headers=author, json={"parent_id": c["id"]}
    )
    assert response.status_code == 409


async def test_delete_restrict_children_and_links(
    client: AsyncClient, author: dict[str, str]
) -> None:
    parent = await _create_topic(client, author, "graphs")
    await _create_topic(client, author, "bfs", parent["id"])
    response = await client.delete(f"/topics/{parent['id']}", headers=author)
    assert response.status_code == 409

    linked = await _create_topic(client, author, "dp")
    await create_question_api(client, author, topic_ids=[linked["id"]])
    response = await client.delete(f"/topics/{linked['id']}", headers=author)
    assert response.status_code == 409

    lonely = await _create_topic(client, author, "bitmask")
    response = await client.delete(f"/topics/{lonely['id']}", headers=author)
    assert response.status_code == 204


async def test_cross_org_isolation(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    await _create_topic(client, author, "mine")
    response = await client.get("/topics", headers=other_org_author)
    assert response.status_code == 200
    assert response.json() == []


async def test_reviewer_cannot_write_topics(
    client: AsyncClient, reviewer: dict[str, str]
) -> None:
    response = await client.post("/topics", headers=reviewer, json={"name": "nope"})
    assert response.status_code == 403


async def test_missing_token_rejected(client: AsyncClient) -> None:
    response = await client.get("/topics")
    assert response.status_code == 401
