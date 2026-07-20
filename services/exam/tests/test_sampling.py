import uuid

from httpx import AsyncClient

from app.clients.question_service import QuestionRef
from tests.conftest import FakeQuestionClient, one_topic_blueprint


def _pool(n: int) -> list[QuestionRef]:
    difficulties = (1, 2, 3)
    return [
        QuestionRef(id=uuid.uuid4(), difficulty=difficulties[i % len(difficulties)])
        for i in range(n)
    ]


async def _create_blueprint(
    client: AsyncClient, author: dict[str, str], topic_id: uuid.UUID, question_count: int = 2
) -> str:
    response = await client.post(
        "/blueprints",
        headers=author,
        json=one_topic_blueprint(topic_id, question_count=question_count),
    )
    assert response.status_code == 201, response.text
    blueprint_id: str = response.json()["id"]
    return blueprint_id


async def _sample(
    client: AsyncClient, headers: dict[str, str], blueprint_id: str, candidate_key: str
) -> tuple[int, dict[str, object]]:
    response = await client.post(
        f"/blueprints/{blueprint_id}/sample",
        headers=headers,
        json={"candidate_key": candidate_key},
    )
    return response.status_code, response.json()


async def test_sample_is_deterministic_per_candidate(
    client: AsyncClient, author: dict[str, str], fake_question_client: FakeQuestionClient
) -> None:
    topic_id = uuid.uuid4()
    fake_question_client.set_pool(topic_id, _pool(8))
    bid = await _create_blueprint(client, author, topic_id, question_count=2)

    status1, body1 = await _sample(client, author, bid, "alice@example.com")
    status2, body2 = await _sample(client, author, bid, "alice@example.com")
    assert status1 == 200 and status2 == 200
    assert body1["selections"] == body2["selections"]  # byte-for-byte reproducible
    assert body1["total_questions"] == 2
    assert len(body1["selections"][0]["question_ids"]) == 2  # type: ignore[index]


async def test_sample_varies_across_candidates(
    client: AsyncClient, author: dict[str, str], fake_question_client: FakeQuestionClient
) -> None:
    topic_id = uuid.uuid4()
    fake_question_client.set_pool(topic_id, _pool(8))
    bid = await _create_blueprint(client, author, topic_id, question_count=2)

    distinct: set[tuple[str, ...]] = set()
    for i in range(10):
        _, body = await _sample(client, author, bid, f"candidate{i}@example.com")
        selection = body["selections"][0]["question_ids"]  # type: ignore[index]
        assert len(selection) == 2  # equivalent structure for every candidate
        distinct.add(tuple(selection))
    # Same blueprint, different candidates → the assigned sets are not all equal.
    assert len(distinct) > 1


async def test_insufficient_pool_returns_409(
    client: AsyncClient, author: dict[str, str], fake_question_client: FakeQuestionClient
) -> None:
    topic_id = uuid.uuid4()
    fake_question_client.set_pool(topic_id, _pool(1))  # blueprint needs 2
    bid = await _create_blueprint(client, author, topic_id, question_count=2)
    status, _ = await _sample(client, author, bid, "x")
    assert status == 409


async def test_caller_token_is_forwarded(
    client: AsyncClient, author: dict[str, str], fake_question_client: FakeQuestionClient
) -> None:
    topic_id = uuid.uuid4()
    fake_question_client.set_pool(topic_id, _pool(4))
    bid = await _create_blueprint(client, author, topic_id, question_count=2)
    await _sample(client, author, bid, "x")
    assert fake_question_client.seen_authorizations
    assert all(
        a == author["Authorization"] for a in fake_question_client.seen_authorizations
    )


async def test_cross_org_sample_denied(
    client: AsyncClient,
    author: dict[str, str],
    other_org_author: dict[str, str],
    fake_question_client: FakeQuestionClient,
) -> None:
    topic_id = uuid.uuid4()
    fake_question_client.set_pool(topic_id, _pool(4))
    bid = await _create_blueprint(client, author, topic_id, question_count=2)
    status, _ = await _sample(client, other_org_author, bid, "x")
    assert status == 404


async def test_reviewer_can_sample(
    client: AsyncClient,
    author: dict[str, str],
    reviewer: dict[str, str],
    fake_question_client: FakeQuestionClient,
) -> None:
    topic_id = uuid.uuid4()
    fake_question_client.set_pool(topic_id, _pool(4))
    bid = await _create_blueprint(client, author, topic_id, question_count=2)
    status, _ = await _sample(client, reviewer, bid, "x")
    assert status == 200
