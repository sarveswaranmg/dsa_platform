import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ai_service import BlueprintSlotSpec, BlueprintSpec, GenerationStatus
from app.clients.question_service import TopicRef, VersionContent
from app.core.security import create_candidate_exam_token
from app.repositories import exam_slot_questions as slots_repo
from app.repositories import exams as exams_repo
from tests.conftest import FakeAiServiceClient, FakeEmailSender, FakeQuestionClient

CANDIDATE_EMAIL = "candidate@example.com"


def _window(start_offset_min: int = 5, end_offset_min: int = 180) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "starts_at": (now + timedelta(minutes=start_offset_min)).isoformat(),
        "ends_at": (now + timedelta(minutes=end_offset_min)).isoformat(),
    }


def _two_slot_spec(topic_a: uuid.UUID, topic_b: uuid.UUID) -> BlueprintSpec:
    return BlueprintSpec(
        topic_mix=[
            BlueprintSlotSpec(
                topic_id=topic_a,
                weight=60,
                difficulty_band="easy",
                difficulty_min=1,
                difficulty_max=2,
                question_count=1,
            ),
            BlueprintSlotSpec(
                topic_id=topic_b,
                weight=40,
                difficulty_band="medium",
                difficulty_min=2,
                difficulty_max=3,
                question_count=1,
            ),
        ],
        total_duration_minutes=60,
        rationale="mock proposal",
    )


async def _schedule(
    client: AsyncClient,
    author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    *,
    start_offset_min: int = 5,
    end_offset_min: int = 180,
) -> str:
    topic_a, topic_b = uuid.uuid4(), uuid.uuid4()
    fake_question_client.topics = [
        TopicRef(id=topic_a, name="Arrays"),
        TopicRef(id=topic_b, name="Graphs"),
    ]
    fake_ai_client.set_blueprint_spec(_two_slot_spec(topic_a, topic_b))
    response = await client.post(
        "/exams/schedule-ai",
        headers=author,
        json={
            "candidate_email": CANDIDATE_EMAIL,
            "candidate_profile_id": str(uuid.uuid4()),
            "target_role": "Backend Engineer",
            "seniority_band": "senior",
            "language_targets": ["python"],
            **_window(start_offset_min, end_offset_min),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending_generation"
    exam_id: str = body["id"]
    return exam_id


async def _succeed_all_slots(
    db_session: AsyncSession,
    fake_ai_client: FakeAiServiceClient,
    *,
    org_id: uuid.UUID,
    exam_id: str,
) -> None:
    slots = await slots_repo.list_by_exam(db_session, org_id=org_id, exam_id=uuid.UUID(exam_id))
    for slot in slots:
        fake_ai_client.set_job_status(
            slot.generation_job_id,
            GenerationStatus(
                status="succeeded",
                question_id=uuid.uuid4(),
                question_version_id=uuid.uuid4(),
                error=None,
            ),
        )


async def test_schedule_ai_creates_pending_generation_exam_with_two_slots(
    client: AsyncClient,
    author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    db_session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    exam_id = await _schedule(client, author, fake_question_client, fake_ai_client)
    slots = await slots_repo.list_by_exam(db_session, org_id=org_id, exam_id=uuid.UUID(exam_id))
    assert len(slots) == 2
    assert [s.ordinal for s in slots] == [1, 2]
    assert all(s.status == "pending" for s in slots)
    # Both calls forwarded the examiner's bearer token.
    assert len(fake_ai_client.generate_calls) == 2
    assert all(a == author["Authorization"] for a in fake_ai_client.seen_authorizations)
    assert all(a == author["Authorization"] for a in fake_question_client.seen_authorizations)


async def test_get_exam_refreshes_to_pending_review_once_all_slots_ready(
    client: AsyncClient,
    author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    db_session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    exam_id = await _schedule(client, author, fake_question_client, fake_ai_client)

    # Still pending: jobs default to "queued".
    response = await client.get(f"/exams/{exam_id}", headers=author)
    assert response.json()["status"] == "pending_generation"

    await _succeed_all_slots(db_session, fake_ai_client, org_id=org_id, exam_id=exam_id)
    response = await client.get(f"/exams/{exam_id}", headers=author)
    body = response.json()
    assert body["status"] == "pending_review"
    assert body["review_deadline_at"] is not None
    assert len(body["slots"]) == 2
    assert all(s["status"] == "ready" and s["question_id"] for s in body["slots"])


async def test_confirm_sends_invite_and_schedules(
    client: AsyncClient,
    author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    fake_email_sender: FakeEmailSender,
    db_session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    exam_id = await _schedule(client, author, fake_question_client, fake_ai_client)
    await _succeed_all_slots(db_session, fake_ai_client, org_id=org_id, exam_id=exam_id)
    await client.get(f"/exams/{exam_id}", headers=author)  # refresh -> pending_review

    response = await client.post(f"/exams/{exam_id}/confirm", headers=author)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "scheduled"
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == CANDIDATE_EMAIL


async def test_confirm_rejected_before_pending_review(
    client: AsyncClient,
    author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
) -> None:
    exam_id = await _schedule(client, author, fake_question_client, fake_ai_client)
    response = await client.post(f"/exams/{exam_id}/confirm", headers=author)
    assert response.status_code == 409


async def test_failed_slot_yields_generation_failed_and_regenerate_recovers(
    client: AsyncClient,
    author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    db_session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    exam_id = await _schedule(client, author, fake_question_client, fake_ai_client)
    slots = await slots_repo.list_by_exam(db_session, org_id=org_id, exam_id=uuid.UUID(exam_id))
    fake_ai_client.set_job_status(
        slots[0].generation_job_id,
        GenerationStatus(
            status="succeeded",
            question_id=uuid.uuid4(),
            question_version_id=uuid.uuid4(),
            error=None,
        ),
    )
    fake_ai_client.set_job_status(
        slots[1].generation_job_id,
        GenerationStatus(status="failed", question_id=None, question_version_id=None, error="boom"),
    )
    response = await client.get(f"/exams/{exam_id}", headers=author)
    body = response.json()
    assert body["status"] == "generation_failed"
    failed = next(s for s in body["slots"] if s["ordinal"] == 2)
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"

    # Overriding the failed slot regenerates it via AI and moves the exam
    # back to pending_generation.
    response = await client.patch(
        f"/exams/{exam_id}/slots/2/regenerate", headers=author
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"

    response = await client.get(f"/exams/{exam_id}", headers=author)
    assert response.json()["status"] == "pending_generation"

    # Succeeding the regenerated slot reaches pending_review again.
    await _succeed_all_slots(db_session, fake_ai_client, org_id=org_id, exam_id=exam_id)
    response = await client.get(f"/exams/{exam_id}", headers=author)
    assert response.json()["status"] == "pending_review"


async def test_regenerate_rejected_once_scheduled(
    client: AsyncClient,
    author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    db_session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    exam_id = await _schedule(client, author, fake_question_client, fake_ai_client)
    await _succeed_all_slots(db_session, fake_ai_client, org_id=org_id, exam_id=exam_id)
    await client.get(f"/exams/{exam_id}", headers=author)
    await client.post(f"/exams/{exam_id}/confirm", headers=author)

    response = await client.patch(f"/exams/{exam_id}/slots/1/regenerate", headers=author)
    assert response.status_code == 409


async def test_auto_confirm_on_read_once_deadline_passes(
    client: AsyncClient,
    author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    fake_email_sender: FakeEmailSender,
    db_session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    exam_id = await _schedule(client, author, fake_question_client, fake_ai_client)
    await _succeed_all_slots(db_session, fake_ai_client, org_id=org_id, exam_id=exam_id)
    await client.get(f"/exams/{exam_id}", headers=author)  # -> pending_review

    # Force the review deadline into the past (monkeypatching the clock is
    # unnecessary here — the deadline is a stored timestamp we can just
    # move back directly).
    exam = await exams_repo.get_by_id(db_session, org_id=org_id, exam_id=uuid.UUID(exam_id))
    assert exam is not None
    exam.review_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    response = await client.get(f"/exams/{exam_id}", headers=author)
    assert response.json()["status"] == "scheduled"
    assert len(fake_email_sender.sent) == 1


async def test_reviewer_cannot_schedule_ai_exam(
    client: AsyncClient,
    author: dict[str, str],
    reviewer: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
) -> None:
    topic_a, topic_b = uuid.uuid4(), uuid.uuid4()
    fake_question_client.topics = [
        TopicRef(id=topic_a, name="Arrays"),
        TopicRef(id=topic_b, name="Graphs"),
    ]
    fake_ai_client.set_blueprint_spec(_two_slot_spec(topic_a, topic_b))
    response = await client.post(
        "/exams/schedule-ai",
        headers=reviewer,
        json={
            "candidate_email": CANDIDATE_EMAIL,
            "candidate_profile_id": str(uuid.uuid4()),
            "target_role": "Backend Engineer",
            "seniority_band": "senior",
            "language_targets": ["python"],
            **_window(),
        },
    )
    assert response.status_code == 403


async def test_cross_org_exam_not_visible(
    client: AsyncClient,
    author: dict[str, str],
    other_org_author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
) -> None:
    exam_id = await _schedule(client, author, fake_question_client, fake_ai_client)
    response = await client.get(f"/exams/{exam_id}", headers=other_org_author)
    assert response.status_code == 404


def _content(version_id: uuid.UUID, question_id: uuid.UUID) -> VersionContent:
    return VersionContent(
        version_id=version_id,
        question_id=question_id,
        version_number=1,
        title="Pinned Question",
        statement_md="Statement.",
        constraints_md="",
        difficulty=1,
        time_limit_ms=2000,
        memory_limit_mb=256,
        starter_code={"python": "pass\n"},
    )


def _candidate_headers(
    exam_id: uuid.UUID, org_id: uuid.UUID, blueprint_version_id: uuid.UUID
) -> dict[str, str]:
    now = datetime.now(UTC)
    token = create_candidate_exam_token(
        invite_id=uuid.uuid4(),
        org_id=org_id,
        exam_id=exam_id,
        blueprint_version_id=blueprint_version_id,
        candidate_email=CANDIDATE_EMAIL,
        not_before=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=3),
    )
    return {"Authorization": f"Bearer {token}"}


async def test_start_session_uses_pinned_slots_not_sampling(
    client: AsyncClient,
    author: dict[str, str],
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    db_session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    exam_id = await _schedule(
        client, author, fake_question_client, fake_ai_client, start_offset_min=-1
    )
    await _succeed_all_slots(db_session, fake_ai_client, org_id=org_id, exam_id=exam_id)
    await client.get(f"/exams/{exam_id}", headers=author)  # -> pending_review
    await client.post(f"/exams/{exam_id}/confirm", headers=author)  # -> scheduled

    exam = await exams_repo.get_by_id(db_session, org_id=org_id, exam_id=uuid.UUID(exam_id))
    assert exam is not None
    slots = await slots_repo.list_by_exam(db_session, org_id=org_id, exam_id=exam.id)
    assert len(slots) == 2
    pinned_version_by_ordinal = {s.ordinal: s.question_version_id for s in slots}

    # Deliberately leave the fake question service's internal pool empty —
    # if the pinned-slot bypass didn't kick in, sampling would have nothing
    # to choose from.
    headers = _candidate_headers(exam.id, org_id, exam.blueprint_version_id)
    response = await client.post("/candidate/session/start", headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["questions"]) == 2
    for q in body["questions"]:
        assert uuid.UUID(q["question_version_id"]) == pinned_version_by_ordinal[q["ordinal"]]
