import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.examiner import Role
from app.repositories import session_events as session_events_repo
from app.repositories import sessions as sessions_repo
from app.repositories import submissions as submissions_repo
from tests.conftest import FakeAiServiceClient, FakeQuestionClient, auth_headers
from tests.test_sessions import _headers, _setup_exam


async def _start_session(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> tuple[uuid.UUID, dict[str, str]]:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=1)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()
    return uuid.UUID(started["id"]), headers


async def test_followup_forks_version_and_repoints_session(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    session_id, headers = await _start_session(client, db_session, fake_question_client, org_id)
    original = await sessions_repo.get_question(
        db_session, org_id=org_id, session_id=session_id, ordinal=1
    )
    assert original is not None
    original_version_id = original.question_version_id

    response = await client.post(
        f"/sessions/{session_id}/followup",
        headers=auth_headers(org_id, Role.PROCTOR),
        json={"ordinal": 1, "modified_constraints_md": "1 <= n <= 10"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_version_id"] == str(original_version_id)
    assert body["new_version_id"] != str(original_version_id)

    updated = await sessions_repo.get_question(
        db_session, org_id=org_id, session_id=session_id, ordinal=1
    )
    assert updated is not None
    assert str(updated.question_version_id) == body["new_version_id"]

    events = await session_events_repo.list_by_session(
        db_session, org_id=org_id, session_id=session_id
    )
    followup_events = [e for e in events if e.type == "followup_pushed"]
    assert len(followup_events) == 1
    assert followup_events[0].payload["new_version_id"] == body["new_version_id"]

    # The candidate can now fetch the new version's content.
    content = await client.get("/candidate/session/questions/1", headers=headers)
    assert content.status_code == 200
    assert content.json()["question_version_id"] == body["new_version_id"]


async def test_submission_before_and_after_followup_bind_to_correct_versions(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    session_id, headers = await _start_session(client, db_session, fake_question_client, org_id)

    before = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": "submit"},
    )
    assert before.status_code == 201
    before_version = before.json()["question_version_id"]

    await client.post(
        f"/sessions/{session_id}/followup",
        headers=auth_headers(org_id, Role.PROCTOR),
        json={"ordinal": 1, "modified_constraints_md": "1 <= n <= 10"},
    )

    after = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": "submit"},
    )
    assert after.status_code == 201
    after_version = after.json()["question_version_id"]

    assert before_version != after_version

    # Each submission row is immutably bound to the version active when it
    # was made — the earlier one is never retroactively rewritten.
    before_row = await submissions_repo.get_by_id(
        db_session, org_id=org_id, submission_id=uuid.UUID(before.json()["id"])
    )
    after_row = await submissions_repo.get_by_id(
        db_session, org_id=org_id, submission_id=uuid.UUID(after.json()["id"])
    )
    assert before_row is not None and str(before_row.question_version_id) == before_version
    assert after_row is not None and str(after_row.question_version_id) == after_version


async def test_followup_survives_missing_ai_lineage(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    org_id: uuid.UUID,
) -> None:
    # Simulates a purely manually-authored question — no succeeded
    # generation_jobs row, so ai's factory has nothing to work from.
    fake_ai_client.followup_factory_error = RuntimeError("404 no lineage")
    session_id, _headers = await _start_session(client, db_session, fake_question_client, org_id)

    response = await client.post(
        f"/sessions/{session_id}/followup",
        headers=auth_headers(org_id, Role.PROCTOR),
        json={"ordinal": 1, "modified_constraints_md": "1 <= n <= 10"},
    )
    # Still succeeds — the forked draft already carries the prior version's
    # test cases forward; the factory is best-effort.
    assert response.status_code == 200, response.text
    assert len(fake_ai_client.followup_factory_calls) == 1


async def test_followup_requires_proctor_role(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    session_id, _headers = await _start_session(client, db_session, fake_question_client, org_id)
    response = await client.post(
        f"/sessions/{session_id}/followup",
        headers=auth_headers(org_id, Role.AUTHOR),
        json={"ordinal": 1, "modified_constraints_md": "1 <= n <= 10"},
    )
    assert response.status_code == 403


async def test_followup_unknown_ordinal_404s(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    session_id, _headers = await _start_session(client, db_session, fake_question_client, org_id)
    response = await client.post(
        f"/sessions/{session_id}/followup",
        headers=auth_headers(org_id, Role.PROCTOR),
        json={"ordinal": 99, "modified_constraints_md": "1 <= n <= 10"},
    )
    assert response.status_code == 404


async def test_replay_returns_ordered_event_stream(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    session_id, headers = await _start_session(client, db_session, fake_question_client, org_id)
    await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": "submit"},
    )

    response = await client.get(
        f"/sessions/{session_id}/replay", headers=auth_headers(org_id, Role.REVIEWER)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [e["seq"] for e in body] == sorted(e["seq"] for e in body)
    assert body[0]["type"] == "question_assigned"
    assert "submission" in [e["type"] for e in body]


async def test_replay_requires_reviewer_role(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    session_id, _headers = await _start_session(client, db_session, fake_question_client, org_id)
    response = await client.get(
        f"/sessions/{session_id}/replay", headers=auth_headers(org_id, Role.PROCTOR)
    )
    assert response.status_code == 403
