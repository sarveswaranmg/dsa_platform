import uuid

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging.contracts import CaseResult, VerdictMessage, VerdictStatus
from app.repositories import sessions as sessions_repo
from app.repositories import submissions as submissions_repo
from app.services.verdicts import process_verdict_message
from tests.conftest import FakeAiServiceClient, FakeQuestionClient
from tests.test_sessions import _headers, _setup_exam


async def test_submit_ac_verdict_signals_difficulty_and_records_band(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    org_id: uuid.UUID,
    redis_client: Redis,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    headers = _headers(exam)
    started = (await client.post("/candidate/session/start", headers=headers)).json()

    await client.get("/candidate/session/questions/1", headers=headers)
    submitted = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": "submit"},
    )
    assert submitted.status_code == 201, submitted.text
    submission_id = uuid.UUID(submitted.json()["id"])
    assigned_version = uuid.UUID(submitted.json()["question_version_id"])

    message = VerdictMessage(
        submission_id=submission_id,
        org_id=org_id,
        status=VerdictStatus.COMPLETED,
        summary_verdict="AC",
        cases=[CaseResult(ordinal=1, verdict="AC", runtime_ms=10, memory_kb=1000)],
    )
    await process_verdict_message(
        db_session, message.model_dump_json(), ai_client=fake_ai_client, redis=redis_client
    )

    assert len(fake_ai_client.difficulty_signals) == 1
    signal = fake_ai_client.difficulty_signals[0]
    assert signal["session_id"] == uuid.UUID(started["id"])
    assert signal["question_version_id"] == assigned_version
    assert signal["verdict"] == "AC"
    assert signal["complexity_hint"] is None
    time_elapsed_pct = float(signal["time_elapsed_pct"])  # type: ignore[arg-type]
    assert 0.0 <= time_elapsed_pct < 0.1  # submitted immediately after viewing

    exam_session = await sessions_repo.get_by_id(
        db_session, org_id=org_id, session_id=uuid.UUID(started["id"])
    )
    assert exam_session is not None
    assert exam_session.current_difficulty == fake_ai_client.difficulty_response.difficulty
    assert (
        exam_session.current_difficulty_band == fake_ai_client.difficulty_response.difficulty_band
    )


async def test_run_mode_submission_never_signals_difficulty(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    org_id: uuid.UUID,
    redis_client: Redis,
) -> None:
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    headers = _headers(exam)
    await client.post("/candidate/session/start", headers=headers)
    await client.get("/candidate/session/questions/1", headers=headers)

    submitted = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": "run"},
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

    assert fake_ai_client.difficulty_signals == []


async def test_unreachable_ai_does_not_break_verdict_persistence(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_question_client: FakeQuestionClient,
    fake_ai_client: FakeAiServiceClient,
    org_id: uuid.UUID,
    redis_client: Redis,
) -> None:
    fake_ai_client.difficulty_signal_error = RuntimeError("ai is down")
    exam = await _setup_exam(db_session, fake_question_client, org_id)
    headers = _headers(exam)
    await client.post("/candidate/session/start", headers=headers)
    await client.get("/candidate/session/questions/1", headers=headers)

    submitted = await client.post(
        "/candidate/session/questions/1/submissions",
        headers=headers,
        json={"language": "python", "source": "print(1)\n", "mode": "submit"},
    )
    assert submitted.status_code == 201
    submission_id = uuid.UUID(submitted.json()["id"])

    message = VerdictMessage(
        submission_id=submission_id,
        org_id=org_id,
        status=VerdictStatus.COMPLETED,
        summary_verdict="AC",
        cases=[CaseResult(ordinal=1, verdict="AC", runtime_ms=10, memory_kb=1000)],
    )
    # Must not raise despite the fake ai_client raising internally.
    await process_verdict_message(
        db_session, message.model_dump_json(), ai_client=fake_ai_client, redis=redis_client
    )

    reloaded = await submissions_repo.get_by_id(
        db_session, org_id=org_id, submission_id=submission_id
    )
    assert reloaded is not None
    assert reloaded.summary_verdict == "AC"
    assert len(fake_ai_client.difficulty_signals) == 1  # it was attempted
