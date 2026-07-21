"""Candidate exam session lifecycle.

Server-authoritative timer: the durable deadline lives on the session row
(any pod reads it), mirrored into Redis as fast, pod-agnostic state. Expiry is
detected lazily on access and locks the session. Assignment samples the exam's
pinned blueprint version on first start and pins each question's version.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.question_service import (
    PublishedQuestionRef,
    QuestionServiceClient,
    VersionContent,
)
from app.core.exceptions import ExamWindowClosed, NotFound, SessionLocked
from app.messaging.sqs import QueuePublisher
from app.models.exam_session import ExamSession, SessionStatus
from app.models.session_question import SessionQuestion
from app.models.submission import Submission
from app.repositories import blueprints as blueprints_repo
from app.repositories import exams as exams_repo
from app.repositories import sessions as sessions_repo
from app.services import submissions as submissions_service
from app.services.sampling import choose

_REDIS_GRACE_SECONDS = 60


def _redis_key(session_id: uuid.UUID) -> str:
    return f"session:{session_id}"


async def _mirror_to_redis(
    redis: Redis, exam_session: ExamSession
) -> None:
    payload = json.dumps(
        {"status": exam_session.status, "deadline": exam_session.deadline_at.isoformat()}
    )
    ttl = max(
        1,
        int((exam_session.deadline_at - datetime.now(UTC)).total_seconds())
        + _REDIS_GRACE_SECONDS,
    )
    await redis.set(_redis_key(exam_session.id), payload, ex=ttl)


async def _lock_if_expired(
    session: AsyncSession, redis: Redis, exam_session: ExamSession
) -> ExamSession:
    if (
        exam_session.status == SessionStatus.IN_PROGRESS.value
        and datetime.now(UTC) >= exam_session.deadline_at
    ):
        # Timer elapsed → auto-lock. Already-enqueued submissions still resolve.
        exam_session.status = SessionStatus.EXPIRED.value
        await session.commit()
        await _mirror_to_redis(redis, exam_session)
    return exam_session


async def start_session(
    session: AsyncSession,
    redis: Redis,
    client: QuestionServiceClient,
    *,
    org_id: uuid.UUID,
    exam_id: uuid.UUID,
    candidate_email: str,
) -> ExamSession:
    exam = await exams_repo.get_by_id(session, org_id=org_id, exam_id=exam_id)
    if exam is None:
        raise NotFound("Exam not found")

    existing = await sessions_repo.get_by_exam(session, org_id=org_id, exam_id=exam_id)
    if existing is not None:
        return await _lock_if_expired(session, redis, existing)  # idempotent resume

    now = datetime.now(UTC)
    if now < exam.starts_at or now >= exam.ends_at:
        raise ExamWindowClosed()

    version = await blueprints_repo.get_version(
        session, org_id=org_id, version_id=exam.blueprint_version_id
    )
    if version is None:
        raise NotFound("Blueprint version not found")

    deadline = min(now + timedelta(minutes=version.total_duration_minutes), exam.ends_at)
    exam_session = await sessions_repo.create_session(
        session,
        org_id=org_id,
        exam_id=exam_id,
        candidate_email=candidate_email,
        started_at=now,
        deadline_at=deadline,
    )

    ordinal = 1
    for index, entry in enumerate(version.topic_mix):
        topic_id = uuid.UUID(str(entry["topic_id"]))
        d_min, d_max = int(entry["difficulty_min"]), int(entry["difficulty_max"])
        count = int(entry["question_count"])

        pool: dict[uuid.UUID, PublishedQuestionRef] = {}
        for difficulty in range(d_min, d_max + 1):
            for ref in await client.list_published_questions_internal(
                org_id=org_id, topic_id=topic_id, difficulty=difficulty
            ):
                pool[ref.question_id] = ref

        ordered = sorted(pool.values(), key=lambda r: r.question_id)
        chosen = choose(
            ordered,
            blueprint_version_id=version.id,
            candidate_key=candidate_email,  # per-candidate seed
            entry_index=index,
            count=count,
        )
        for ref in chosen:
            await sessions_repo.add_question(
                session,
                org_id=org_id,
                session_id=exam_session.id,
                ordinal=ordinal,
                question_id=ref.question_id,
                question_version_id=ref.published_version_id,
            )
            ordinal += 1

    await session.commit()
    await _mirror_to_redis(redis, exam_session)
    return exam_session


async def get_session(
    session: AsyncSession, redis: Redis, *, org_id: uuid.UUID, exam_id: uuid.UUID
) -> tuple[ExamSession, list[SessionQuestion]]:
    exam_session = await sessions_repo.get_by_exam(session, org_id=org_id, exam_id=exam_id)
    if exam_session is None:
        raise NotFound("Session not started")
    await _lock_if_expired(session, redis, exam_session)
    questions = list(
        await sessions_repo.list_questions(
            session, org_id=org_id, session_id=exam_session.id
        )
    )
    return exam_session, questions


async def get_question_content(
    session: AsyncSession,
    redis: Redis,
    client: QuestionServiceClient,
    *,
    org_id: uuid.UUID,
    exam_id: uuid.UUID,
    ordinal: int,
) -> tuple[SessionQuestion, VersionContent]:
    exam_session = await sessions_repo.get_by_exam(session, org_id=org_id, exam_id=exam_id)
    if exam_session is None:
        raise NotFound("Session not started")
    assigned = await sessions_repo.get_question(
        session, org_id=org_id, session_id=exam_session.id, ordinal=ordinal
    )
    if assigned is None:
        raise NotFound("Question not found in this session")
    content = await client.get_version_content(
        org_id=org_id, version_id=assigned.question_version_id
    )
    return assigned, content


async def submit(
    session: AsyncSession,
    redis: Redis,
    client: QuestionServiceClient,
    publisher: QueuePublisher,
    *,
    org_id: uuid.UUID,
    exam_id: uuid.UUID,
    ordinal: int,
    language: str,
    source: str,
    mode: str = "submit",
) -> Submission:
    exam_session = await sessions_repo.get_by_exam(session, org_id=org_id, exam_id=exam_id)
    if exam_session is None:
        raise NotFound("Session not started")
    await _lock_if_expired(session, redis, exam_session)
    if exam_session.status != SessionStatus.IN_PROGRESS.value:
        raise SessionLocked()

    assigned = await sessions_repo.get_question(
        session, org_id=org_id, session_id=exam_session.id, ordinal=ordinal
    )
    if assigned is None:
        raise NotFound("Question not found in this session")

    return await submissions_service.create_and_enqueue(
        session,
        client,
        publisher,
        org_id=org_id,
        exam_id=exam_id,
        question_version_id=assigned.question_version_id,
        language=language,
        source=source,
        session_id=exam_session.id,
        mode=mode,
    )
