import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.question_service import PublishedQuestionRef, VersionContent
from app.core.security import create_candidate_exam_token
from app.messaging.sqs import SqsPublisher
from app.models.exam import Exam
from app.models.exam_session import SessionStatus
from app.repositories import blueprints as blueprints_repo
from app.repositories import exams as exams_repo
from app.repositories import sessions as sessions_repo
from app.repositories import submissions as submissions_repo
from tests.conftest import FakePublisher, FakeQuestionClient

CANDIDATE_EMAIL = "cand@example.com"


@pytest.fixture
def captured_jobs(
    monkeypatch: pytest.MonkeyPatch, fake_publisher: FakePublisher
) -> Iterator[FakePublisher]:
    """Capture jobs the submit route publishes, without touching real SQS."""
    monkeypatch.setattr(SqsPublisher, "send", fake_publisher.send)
    yield fake_publisher


def _content(version_id: uuid.UUID, question_id: uuid.UUID) -> VersionContent:
    return VersionContent(
        version_id=version_id,
        question_id=question_id,
        version_number=1,
        title="Add Two Numbers",
        statement_md="Read a and b, print a+b.",
        constraints_md="1 <= a,b <= 100",
        difficulty=1,
        time_limit_ms=2000,
        memory_limit_mb=256,
        starter_code={"python": "pass\n"},
    )


async def _setup_exam(
    db_session: AsyncSession,
    fake: FakeQuestionClient,
    org_id: uuid.UUID,
    *,
    question_count: int = 2,
    duration_minutes: int = 60,
    start_offset_min: int = -1,
    end_offset_min: int = 120,
) -> Exam:
    """Blueprint version with a one-topic mix + an exam, and a published-question
    pool (count+1 candidates) registered in the fake question service."""
    topic_id = uuid.uuid4()
    blueprint = await blueprints_repo.create_blueprint(db_session, org_id=org_id, name="BP")
    version = await blueprints_repo.create_version(
        db_session,
        org_id=org_id,
        blueprint_id=blueprint.id,
        version_number=1,
        target_role="BE",
        experience_band="senior",
        total_duration_minutes=duration_minutes,
        topic_mix=[
            {
                "topic_id": str(topic_id),
                "weight": 100,
                "difficulty_min": 1,
                "difficulty_max": 1,
                "question_count": question_count,
            }
        ],
    )
    blueprint.current_version_id = version.id
    now = datetime.now(UTC)
    exam = await exams_repo.create_exam(
        db_session,
        org_id=org_id,
        blueprint_id=blueprint.id,
        blueprint_version_id=version.id,
        candidate_email=CANDIDATE_EMAIL,
        starts_at=now + timedelta(minutes=start_offset_min),
        ends_at=now + timedelta(minutes=end_offset_min),
    )
    await db_session.commit()

    refs = []
    for _ in range(question_count + 1):
        qid, vid = uuid.uuid4(), uuid.uuid4()
        refs.append(
            PublishedQuestionRef(question_id=qid, published_version_id=vid, difficulty=1)
        )
        fake.set_version(_content(vid, qid))
    fake.set_internal_pool(topic_id, refs)
    return exam


def _headers(exam: Exam) -> dict[str, str]:
    now = datetime.now(UTC)
    token = create_candidate_exam_token(
        invite_id=uuid.uuid4(),
        org_id=exam.org_id,
        exam_id=exam.id,
        blueprint_version_id=exam.blueprint_version_id,
        candidate_email=CANDIDATE_EMAIL,
        not_before=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=3),
    )
    return {"Authorization": f"Bearer {token}"}


async def test_start_assigns_questions_and_sets_timer(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=2)
    response = await client.post("/candidate/session/start", headers=_headers(exam))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == SessionStatus.IN_PROGRESS.value
    assert len(body["questions"]) == 2
    assert [q["ordinal"] for q in body["questions"]] == [1, 2]
    assert all(q["question_version_id"] for q in body["questions"])  # versions pinned
    assert 0 < body["remaining_seconds"] <= 60 * 60


async def test_start_before_window_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(
        db_session, fake_question_client, org_id, start_offset_min=30, end_offset_min=120
    )
    response = await client.post("/candidate/session/start", headers=_headers(exam))
    assert response.status_code == 403


async def test_start_after_window_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(
        db_session, fake_question_client, org_id, start_offset_min=-120, end_offset_min=-60
    )
    response = await client.post("/candidate/session/start", headers=_headers(exam))
    assert response.status_code == 403


async def test_start_is_idempotent_and_deterministic(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=2)
    headers = _headers(exam)
    first = (await client.post("/candidate/session/start", headers=headers)).json()
    second = (await client.post("/candidate/session/start", headers=headers)).json()
    assert first["id"] == second["id"]  # resumed, not re-created
    assert first["questions"] == second["questions"]  # same assignment


async def test_deadline_capped_by_exam_window(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    # Blueprint allows 60m but only ~10m of the window remains.
    exam = await _setup_exam(
        db_session, fake_question_client, org_id, duration_minutes=60, end_offset_min=10
    )
    body = (await client.post("/candidate/session/start", headers=_headers(exam))).json()
    assert body["remaining_seconds"] <= 10 * 60


async def test_fetch_question_content(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    headers = _headers(exam)
    await client.post("/candidate/session/start", headers=headers)

    response = await client.get("/candidate/session/questions/1", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["ordinal"] == 1
    assert body["title"] == "Add Two Numbers"
    assert body["starter_code"] == {"python": "pass\n"}

    missing = await client.get("/candidate/session/questions/99", headers=headers)
    assert missing.status_code == 404


async def test_submit_records_session_and_version(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    captured_jobs: FakePublisher,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()
    assigned_version = started["questions"][0]["question_version_id"]

    response = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["question_version_id"] == assigned_version  # pinned version stored

    stored = await submissions_repo.get_by_id(
        db_session, org_id=org_id, submission_id=uuid.UUID(body["id"])
    )
    assert stored is not None
    assert str(stored.session_id) == started["id"]  # linked to the session
    assert len(captured_jobs.sent) == 1  # enqueued to the judge


async def test_run_mode_grades_only_sample_cases(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    captured_jobs: FakePublisher,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    headers = _headers(exam)
    await client.post("/candidate/session/start", headers=headers)

    run = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": "run"},
    )
    assert run.status_code == 201
    assert run.json()["mode"] == "run"
    job = json.loads(captured_jobs.sent[0][1])
    assert [c["ordinal"] for c in job["cases"]] == [1]  # sample case only


async def test_submit_mode_grades_every_case(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    captured_jobs: FakePublisher,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    headers = _headers(exam)
    await client.post("/candidate/session/start", headers=headers)

    submitted = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": "submit"},
    )
    assert submitted.status_code == 201
    assert submitted.json()["mode"] == "submit"
    job = json.loads(captured_jobs.sent[0][1])
    assert [c["ordinal"] for c in job["cases"]] == [1, 2]  # sample + hidden


async def test_timer_expiry_locks_session_and_blocks_submit(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    captured_jobs: FakePublisher,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    headers = _headers(exam)
    await client.post("/candidate/session/start", headers=headers)

    # Wind the server-side deadline into the past.
    exam_session = await sessions_repo.get_by_exam(
        db_session, org_id=org_id, exam_id=exam.id
    )
    assert exam_session is not None
    exam_session.deadline_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    submit = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n"},
    )
    assert submit.status_code == 409  # locked
    assert captured_jobs.sent == []  # nothing enqueued after expiry

    state = (await client.get("/candidate/session", headers=headers)).json()
    assert state["status"] == SessionStatus.EXPIRED.value
    assert state["remaining_seconds"] == 0


async def test_submit_after_lock_stays_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    captured_jobs: FakePublisher,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    headers = _headers(exam)
    await client.post("/candidate/session/start", headers=headers)
    exam_session = await sessions_repo.get_by_exam(
        db_session, org_id=org_id, exam_id=exam.id
    )
    assert exam_session is not None
    exam_session.deadline_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    for _ in range(2):
        response = await client.post(
            "/candidate/session/questions/1/submissions",
            headers=headers,
            json={"language": "python", "source": "print(1)\n"},
        )
        assert response.status_code == 409


async def test_resume_after_disconnect(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=2)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()

    # "Reconnect": a fresh request rebuilds everything from server state.
    resumed = (await client.get("/candidate/session", headers=headers)).json()
    assert resumed["id"] == started["id"]
    assert resumed["questions"] == started["questions"]
    assert resumed["status"] == SessionStatus.IN_PROGRESS.value
    assert resumed["remaining_seconds"] <= started["remaining_seconds"]
    assert resumed["deadline_at"] == started["deadline_at"]  # timer never restarts


async def test_get_session_before_start(client: AsyncClient, db_session: AsyncSession,
                                        fake_question_client: FakeQuestionClient,
                                        org_id: uuid.UUID) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    response = await client.get("/candidate/session", headers=_headers(exam))
    assert response.status_code == 404


async def test_other_org_token_cannot_reach_exam(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    now = datetime.now(UTC)
    foreign = create_candidate_exam_token(
        invite_id=uuid.uuid4(),
        org_id=uuid.uuid4(),  # different org, same exam id
        exam_id=exam.id,
        blueprint_version_id=exam.blueprint_version_id,
        candidate_email=CANDIDATE_EMAIL,
        not_before=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=3),
    )
    response = await client.post(
        "/candidate/session/start", headers={"Authorization": f"Bearer {foreign}"}
    )
    assert response.status_code == 404


async def test_session_routes_require_candidate_token(
    client: AsyncClient, author: dict[str, str]
) -> None:
    # Examiner token on the candidate plane is rejected (two token planes).
    assert (await client.get("/candidate/session", headers=author)).status_code == 401
    assert (await client.post("/candidate/session/start", headers=author)).status_code == 401
