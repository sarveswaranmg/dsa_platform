import uuid

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging.contracts import CaseResult, VerdictMessage, VerdictStatus
from app.repositories import session_events as session_events_repo
from app.services import session_events as session_events_service
from app.services.verdicts import process_verdict_message
from tests.conftest import FakeAiServiceClient, FakeQuestionClient
from tests.test_sessions import _headers, _setup_exam


async def _real_session_id(
    client: AsyncClient, db_session: AsyncSession, fake: FakeQuestionClient, org_id: uuid.UUID
) -> uuid.UUID:
    """session_events.session_id is FK'd to exam_sessions — these lower-level
    tests still need a real, started session to attach events to."""
    exam = await _setup_exam(db_session, fake, org_id, question_count=1)
    started = (await client.post("/candidate/session/start", headers=_headers(exam))).json()
    return uuid.UUID(started["id"])


async def test_create_event_assigns_strictly_increasing_seq(
    client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    session_id = await _real_session_id(client, db_session, fake_question_client, org_id)
    first = await session_events_service.emit(
        db_session,
        redis_client,
        org_id=org_id,
        session_id=session_id,
        type="code_snapshot",
        payload={"ordinal": 1, "source": "a"},
    )
    second = await session_events_service.emit(
        db_session,
        redis_client,
        org_id=org_id,
        session_id=session_id,
        type="code_snapshot",
        payload={"ordinal": 1, "source": "b"},
    )
    # A question_assigned event was already emitted by start_session (seq 1),
    # so these two land at 2 and 3.
    assert second.seq == first.seq + 1

    events = await session_events_repo.list_by_session(
        db_session, org_id=org_id, session_id=session_id
    )
    snapshot_events = [e for e in events if e.type == "code_snapshot"]
    assert [e.seq for e in snapshot_events] == [first.seq, second.seq]
    assert [e.payload["source"] for e in snapshot_events] == ["a", "b"]


async def test_different_sessions_have_independent_sequences(
    client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    session_a = await _real_session_id(client, db_session, fake_question_client, org_id)
    session_b = await _real_session_id(client, db_session, fake_question_client, org_id)
    event_a = await session_events_service.emit(
        db_session, redis_client, org_id=org_id, session_id=session_a,
        type="code_snapshot", payload={},
    )
    event_b = await session_events_service.emit(
        db_session, redis_client, org_id=org_id, session_id=session_b,
        type="code_snapshot", payload={},
    )
    # Both sessions already have one question_assigned event (seq 1) from
    # start_session — each session's new event lands at seq 2 independently.
    assert event_a.seq == event_b.seq == 2


async def test_start_session_emits_question_assigned_events(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=2)
    started = (
        await client.post("/candidate/session/start", headers=_headers(exam))
    ).json()

    events = await session_events_repo.list_by_session(
        db_session, org_id=org_id, session_id=uuid.UUID(started["id"])
    )
    assigned_events = [e for e in events if e.type == "question_assigned"]
    assert len(assigned_events) == 2
    assert [e.seq for e in assigned_events] == [1, 2]
    assert {e.payload["ordinal"] for e in assigned_events} == {1, 2}


async def test_submission_and_verdict_events_recorded(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    redis_client: Redis,
    org_id: uuid.UUID,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id, question_count=1)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()

    submitted = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": "submit"},
    )
    assert submitted.status_code == 201

    message = VerdictMessage(
        submission_id=uuid.UUID(submitted.json()["id"]),
        org_id=org_id,
        status=VerdictStatus.COMPLETED,
        summary_verdict="AC",
        cases=[CaseResult(ordinal=1, verdict="AC", runtime_ms=10, memory_kb=1000)],
    )
    await process_verdict_message(
        db_session, message.model_dump_json(), ai_client=fake_ai_client, redis=redis_client
    )

    session_id = uuid.UUID(started["id"])
    events = await session_events_repo.list_by_session(
        db_session, org_id=org_id, session_id=session_id
    )
    types = [e.type for e in events]
    assert "question_assigned" in types
    assert "submission" in types
    assert "verdict" in types
    # Strictly ordered — question_assigned always precedes the submission
    # it's about, which precedes its verdict.
    assert types.index("question_assigned") < types.index("submission") < types.index("verdict")


async def test_emit_publishes_to_the_session_channel(
    client: AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    fake_question_client: FakeQuestionClient,
    org_id: uuid.UUID,
) -> None:
    session_id = await _real_session_id(client, db_session, fake_question_client, org_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"ex:session-events:{session_id}")
    try:
        await session_events_service.emit(
            db_session,
            redis_client,
            org_id=org_id,
            session_id=session_id,
            type="code_snapshot",
            payload={"ordinal": 1, "source": "x"},
        )
        message = None
        for _ in range(5):
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None:
                break
        assert message is not None
        assert "code_snapshot" in message["data"]
    finally:
        await pubsub.unsubscribe(f"ex:session-events:{session_id}")
        await pubsub.aclose()  # type: ignore[no-untyped-call]
