import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import FakeQuestionClient
from tests.test_sessions import _headers, _setup_exam


async def test_lists_assigned_questions_no_auth_required(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=2)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()
    session_id = started["id"]

    await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n"},
    )

    response = await client.get(
        f"/internal/sessions/{session_id}/questions", params={"org_id": str(org_id)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [q["ordinal"] for q in body] == [1, 2]
    assert len(body[0]["submissions"]) == 1
    assert body[0]["submissions"][0]["language"] == "python"
    assert body[1]["submissions"] == []  # assigned but never submitted to


async def test_scoped_by_org(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=1)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()

    response = await client.get(
        f"/internal/sessions/{started['id']}/questions",
        params={"org_id": str(uuid.uuid4())},  # foreign org
    )
    assert response.status_code == 404


async def test_unknown_session_not_found(client: AsyncClient, org_id: uuid.UUID) -> None:
    response = await client.get(
        f"/internal/sessions/{uuid.uuid4()}/questions", params={"org_id": str(org_id)}
    )
    assert response.status_code == 404


@pytest.mark.parametrize("mode", ["run", "submit"])
async def test_submission_records_full_history(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
    mode: str,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=1)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()

    await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": mode},
    )

    response = await client.get(
        f"/internal/sessions/{started['id']}/questions", params={"org_id": str(org_id)}
    )
    body = response.json()
    assert body[0]["submissions"][0]["mode"] == mode
