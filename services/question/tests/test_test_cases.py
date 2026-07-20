from typing import Any

from httpx import AsyncClient

from tests.conftest import create_question_api


async def _add_test_case(
    client: AsyncClient, headers: dict[str, str], question_id: str, **body: object
) -> dict[str, Any]:
    response = await client.post(
        f"/questions/{question_id}/test-cases", headers=headers, json=body
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


async def test_upload_download_round_trip(
    client: AsyncClient, author: dict[str, str], s3_bucket: None
) -> None:
    question = await create_question_api(client, author)
    tc = await _add_test_case(client, author, question["id"], is_sample=True)

    async with AsyncClient() as external:
        put_input = await external.put(tc["upload_input_url"], content=b"3\n1 2 3\n")
        put_output = await external.put(tc["upload_output_url"], content=b"6\n")
        assert put_input.status_code == 200, put_input.text
        assert put_output.status_code == 200, put_output.text

        listing = (
            await client.get(f"/questions/{question['id']}/test-cases", headers=author)
        ).json()
        assert len(listing) == 1
        got_input = await external.get(listing[0]["input_url"])
        got_output = await external.get(listing[0]["output_url"])
        assert got_input.content == b"3\n1 2 3\n"
        assert got_output.content == b"6\n"


async def test_ordinals_autoincrement_and_conflict(
    client: AsyncClient, author: dict[str, str]
) -> None:
    question = await create_question_api(client, author)
    first = await _add_test_case(client, author, question["id"])
    second = await _add_test_case(client, author, question["id"])
    assert (first["ordinal"], second["ordinal"]) == (1, 2)

    response = await client.post(
        f"/questions/{question['id']}/test-cases", headers=author, json={"ordinal": 2}
    )
    assert response.status_code == 409


async def test_adding_test_case_to_published_question_copies_version(
    client: AsyncClient, author: dict[str, str]
) -> None:
    question = await create_question_api(client, author)
    qid = question["id"]
    existing = await _add_test_case(client, author, qid)
    published = (await client.post(f"/questions/{qid}/publish", headers=author)).json()
    v1_id = published["published_version_id"]

    added = await _add_test_case(client, author, qid)
    # New test case landed on a fresh version, not the published one.
    assert added["question_version_id"] != v1_id

    detail = (await client.get(f"/questions/{qid}", headers=author)).json()
    assert detail["current_version"]["version_number"] == 2
    assert detail["published_version_id"] == v1_id

    # Current version carries the copied case plus the new one.
    listing = (await client.get(f"/questions/{qid}/test-cases", headers=author)).json()
    assert [tc["ordinal"] for tc in listing] == [1, 2]
    copied = next(tc for tc in listing if tc["ordinal"] == existing["ordinal"])
    assert copied["input_s3_key"] == existing["input_s3_key"]  # S3 object shared
    assert copied["id"] != existing["id"]


async def test_delete_test_case_on_published_question_copies_version(
    client: AsyncClient, author: dict[str, str]
) -> None:
    question = await create_question_api(client, author)
    qid = question["id"]
    tc = await _add_test_case(client, author, qid)
    await client.post(f"/questions/{qid}/publish", headers=author)

    response = await client.delete(
        f"/questions/{qid}/test-cases/{tc['id']}", headers=author
    )
    assert response.status_code == 204

    detail = (await client.get(f"/questions/{qid}", headers=author)).json()
    assert detail["current_version"]["version_number"] == 2
    assert (
        await client.get(f"/questions/{qid}/test-cases", headers=author)
    ).json() == []


async def test_cross_org_test_case_denied(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    question = await create_question_api(client, author)
    response = await client.post(
        f"/questions/{question['id']}/test-cases", headers=other_org_author, json={}
    )
    assert response.status_code == 404


async def test_reviewer_cannot_add_test_case(
    client: AsyncClient, author: dict[str, str], reviewer: dict[str, str]
) -> None:
    question = await create_question_api(client, author)
    response = await client.post(
        f"/questions/{question['id']}/test-cases", headers=reviewer, json={}
    )
    assert response.status_code == 403
