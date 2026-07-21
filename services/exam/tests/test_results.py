import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging.contracts import (
    CaseResult,
    VerdictMessage,
    VerdictStatus,
)
from app.models.examiner import Role
from app.services import submissions as submissions_service
from app.services.verdicts import process_verdict_message
from tests.conftest import FakePublisher, FakeQuestionClient, auth_headers
from tests.test_sessions import _headers, _setup_exam

SOURCE = "a,b=map(int,input().split())\nprint(a+b)\n"


async def _submitted_exam(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Start a session, submit once, and persist a verdict. Returns
    (exam_id, submission_id)."""
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    started = await client.post("/candidate/session/start", headers=_headers(exam))
    # Submit against a version the session actually assigned, so the fake
    # question service has test cases for it.
    assigned_version = started.json()["questions"][0]["question_version_id"]

    submission = await submissions_service.create_and_enqueue(
        db_session,
        fake_question_client,
        FakePublisher(),
        org_id=org_id,
        exam_id=exam.id,
        question_version_id=uuid.UUID(assigned_version),
        language="python",
        source=SOURCE,
    )
    message = VerdictMessage(
        submission_id=submission.id,
        org_id=org_id,
        status=VerdictStatus.COMPLETED,
        summary_verdict="AC",
        cases=[
            CaseResult(ordinal=1, verdict="AC", runtime_ms=20, memory_kb=15132),
            CaseResult(ordinal=2, verdict="AC", runtime_ms=22, memory_kb=15140),
        ],
    )
    await process_verdict_message(db_session, message.model_dump_json())
    return exam.id, submission.id


async def test_lists_submissions_for_an_exam(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam_id, submission_id = await _submitted_exam(
        client, db_session, fake_question_client, org_id
    )
    response = await client.get(
        f"/exams/{exam_id}/submissions", headers=auth_headers(org_id, Role.REVIEWER)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(submission_id)
    assert body[0]["summary_verdict"] == "AC"
    assert "source" not in body[0]  # the list view never carries code


async def test_detail_returns_code_and_case_verdicts(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    _, submission_id = await _submitted_exam(
        client, db_session, fake_question_client, org_id
    )
    response = await client.get(
        f"/submissions/{submission_id}", headers=auth_headers(org_id, Role.REVIEWER)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == SOURCE  # read-only Monaco viewer needs this
    assert [c["ordinal"] for c in body["cases"]] == [1, 2]
    assert body["cases"][0]["verdict"] == "AC"
    assert body["cases"][0]["memory_kb"] == 15132


async def test_admin_and_proctor_may_read_results(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam_id, _ = await _submitted_exam(
        client, db_session, fake_question_client, org_id
    )
    for role in (Role.ADMIN, Role.PROCTOR):
        response = await client.get(
            f"/exams/{exam_id}/submissions", headers=auth_headers(org_id, role)
        )
        assert response.status_code == 200, f"{role} should be able to read results"


async def test_author_is_denied_results(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam_id, submission_id = await _submitted_exam(
        client, db_session, fake_question_client, org_id
    )
    listed = await client.get(
        f"/exams/{exam_id}/submissions", headers=auth_headers(org_id, Role.AUTHOR)
    )
    assert listed.status_code == 403
    detail = await client.get(
        f"/submissions/{submission_id}", headers=auth_headers(org_id, Role.AUTHOR)
    )
    assert detail.status_code == 403


async def test_cross_org_results_are_not_found(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam_id, submission_id = await _submitted_exam(
        client, db_session, fake_question_client, org_id
    )
    other = auth_headers(uuid.uuid4(), Role.REVIEWER)
    assert (await client.get(f"/exams/{exam_id}/submissions", headers=other)).status_code == 404
    assert (await client.get(f"/submissions/{submission_id}", headers=other)).status_code == 404


async def test_results_require_a_token(client: AsyncClient) -> None:
    assert (await client.get(f"/exams/{uuid.uuid4()}/submissions")).status_code == 401
    assert (await client.get(f"/submissions/{uuid.uuid4()}")).status_code == 401
