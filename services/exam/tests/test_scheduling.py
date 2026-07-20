import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.conftest import FakeEmailSender, one_topic_blueprint


async def _create_blueprint(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/blueprints", headers=headers, json=one_topic_blueprint(uuid.uuid4())
    )
    assert response.status_code == 201, response.text
    blueprint_id: str = response.json()["id"]
    return blueprint_id


def _window(start_offset_min: int = -1, end_offset_min: int = 60) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "starts_at": (now + timedelta(minutes=start_offset_min)).isoformat(),
        "ends_at": (now + timedelta(minutes=end_offset_min)).isoformat(),
    }


async def test_schedule_exam_happy(
    client: AsyncClient, author: dict[str, str], fake_email_sender: FakeEmailSender
) -> None:
    blueprint_id = await _create_blueprint(client, author)
    response = await client.post(
        "/exams",
        headers=author,
        json={
            "candidate_email": "Candidate@Example.com",
            "blueprint_id": blueprint_id,
            **_window(),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["candidate_email"] == "candidate@example.com"  # normalized
    assert body["status"] == "scheduled"
    assert body["blueprint_version_id"]  # pinned
    assert body["invite"]["status"] == "pending"
    assert body["invite_link"] and "token=" in body["invite_link"]

    # Email was "sent" with the link.
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == "candidate@example.com"
    assert "token=" in fake_email_sender.sent[0].body


async def test_schedule_blueprint_not_found(
    client: AsyncClient, author: dict[str, str]
) -> None:
    response = await client.post(
        "/exams",
        headers=author,
        json={
            "candidate_email": "c@example.com",
            "blueprint_id": str(uuid.uuid4()),
            **_window(),
        },
    )
    assert response.status_code == 404


async def test_schedule_cross_org_blueprint_denied(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    blueprint_id = await _create_blueprint(client, author)
    response = await client.post(
        "/exams",
        headers=other_org_author,
        json={
            "candidate_email": "c@example.com",
            "blueprint_id": blueprint_id,
            **_window(),
        },
    )
    assert response.status_code == 404


async def test_schedule_end_before_start_rejected(
    client: AsyncClient, author: dict[str, str]
) -> None:
    blueprint_id = await _create_blueprint(client, author)
    response = await client.post(
        "/exams",
        headers=author,
        json={
            "candidate_email": "c@example.com",
            "blueprint_id": blueprint_id,
            **_window(start_offset_min=60, end_offset_min=30),
        },
    )
    assert response.status_code == 422


async def test_schedule_window_already_ended_rejected(
    client: AsyncClient, author: dict[str, str]
) -> None:
    blueprint_id = await _create_blueprint(client, author)
    response = await client.post(
        "/exams",
        headers=author,
        json={
            "candidate_email": "c@example.com",
            "blueprint_id": blueprint_id,
            **_window(start_offset_min=-120, end_offset_min=-60),
        },
    )
    assert response.status_code == 422


async def test_reviewer_cannot_schedule(
    client: AsyncClient, author: dict[str, str], reviewer: dict[str, str]
) -> None:
    blueprint_id = await _create_blueprint(client, author)
    response = await client.post(
        "/exams",
        headers=reviewer,
        json={
            "candidate_email": "c@example.com",
            "blueprint_id": blueprint_id,
            **_window(),
        },
    )
    assert response.status_code == 403


async def test_list_and_get_exam_scoped_to_org(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    blueprint_id = await _create_blueprint(client, author)
    created = await client.post(
        "/exams",
        headers=author,
        json={"candidate_email": "c@example.com", "blueprint_id": blueprint_id, **_window()},
    )
    exam_id = created.json()["id"]

    assert len((await client.get("/exams", headers=author)).json()) == 1
    assert (await client.get("/exams", headers=other_org_author)).json() == []
    assert (await client.get(f"/exams/{exam_id}", headers=author)).status_code == 200
    assert (
        await client.get(f"/exams/{exam_id}", headers=other_org_author)
    ).status_code == 404
