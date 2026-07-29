import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.examiner import Role
from app.models.org import Org
from app.repositories import examiners as examiners_repo
from app.repositories import sessions as sessions_repo
from tests.conftest import FakeEmailSender, FakeQuestionClient
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


async def test_session_context_returns_candidate_and_blueprint_info(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=1)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()

    response = await client.get(
        f"/internal/sessions/{started['id']}", params={"org_id": str(org_id)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate_email"] == exam.candidate_email
    assert body["target_role"] == "BE"
    assert body["experience_band"] == "senior"
    assert body["candidate_profile_id"] is None  # Mode 1 (manual) exam


async def test_session_context_unknown_session_not_found(
    client: AsyncClient, org_id: uuid.UUID
) -> None:
    response = await client.get(
        f"/internal/sessions/{uuid.uuid4()}", params={"org_id": str(org_id)}
    )
    assert response.status_code == 404


async def test_attach_hiring_report_writes_columns_and_emails_reviewers_and_admins(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    fake_email_sender: FakeEmailSender,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=1)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()

    # examiners.org_id FKs to orgs — insert one with a matching id so the
    # test's fixture-generated org_id is a valid foreign key.
    db_session.add(Org(id=org_id, name="Test Org"))
    await db_session.flush()

    for role, email in [
        (Role.REVIEWER, "reviewer@example.com"),
        (Role.ADMIN, "admin@example.com"),
        (Role.PROCTOR, "proctor@example.com"),  # should NOT be emailed
        (Role.AUTHOR, "author@example.com"),  # should NOT be emailed
    ]:
        await examiners_repo.create_examiner(
            db_session,
            org_id=org_id,
            email=email,
            password_hash="x",
            role=role,
            totp_secret="x",
        )
    await db_session.commit()

    report_json = {"seniority_match": "SDE-2", "recommendation": "proceed"}
    response = await client.post(
        f"/internal/sessions/{started['id']}/report",
        json={"org_id": str(org_id), "report_json": report_json, "recommendation": "proceed"},
    )
    assert response.status_code == 204, response.text

    exam_session = await sessions_repo.get_by_id(
        db_session, org_id=org_id, session_id=uuid.UUID(started["id"])
    )
    assert exam_session is not None
    assert exam_session.hiring_report_json == report_json
    assert exam_session.hiring_report_recommendation == "proceed"
    assert exam_session.hiring_report_generated_at is not None

    recipients = {m.to for m in fake_email_sender.sent}
    assert recipients == {"reviewer@example.com", "admin@example.com"}


async def test_attach_hiring_report_unknown_session_not_found(
    client: AsyncClient, org_id: uuid.UUID
) -> None:
    response = await client.post(
        f"/internal/sessions/{uuid.uuid4()}/report",
        json={"org_id": str(org_id), "report_json": {}, "recommendation": "proceed"},
    )
    assert response.status_code == 404
