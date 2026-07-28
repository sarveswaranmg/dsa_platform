"""Phase 2 Slice 4: Mode 2 profile-driven exam scheduling. See
docs/design-mode2-scheduling.md.

Rather than building new `ai`-side aggregate endpoints, this fans out by
calling Slice 2's *existing, already-tested* `POST /questions/generate`
once per blueprint slot, and aggregates status here (in exam, which has to
track which question ended up in which slot anyway) by polling each slot's
job via Slice 2's existing `GET /questions/generate/{id}`. Every call
forwards the acting examiner's bearer token — every entry point here runs
inside some live, freshly-authenticated request, so there's always a valid
token to forward (no new internal/token-minting machinery needed).

Auto-confirm is a lazy check on read, not a background timer:
`refresh_ai_exam` is called first by every Mode 2 endpoint, and confirms the
exam right there once the review deadline has passed.
"""

import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ai_service import AiServiceClient
from app.clients.question_service import QuestionServiceClient
from app.core.config import get_settings
from app.core.exceptions import InvalidExamStatus, InvalidWindow, NotFound
from app.models.exam import Exam, ExamStatus
from app.models.exam_slot_question import ExamSlotQuestion, SlotStatus
from app.notifications.email import EmailSender
from app.repositories import exam_slot_questions as slots_repo
from app.repositories import exams as exams_repo
from app.schemas.blueprint import TopicMixEntry
from app.services import blueprints as blueprints_service
from app.services import scheduling as scheduling_service


async def schedule_ai_exam(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    ai_client: AiServiceClient,
    question_client: QuestionServiceClient,
    authorization: str,
    candidate_email: str,
    candidate_profile_id: uuid.UUID,
    target_role: str,
    seniority_band: str,
    language_targets: list[str],
    starts_at: datetime,
    ends_at: datetime,
) -> Exam:
    now = datetime.now(UTC)
    if ends_at <= now:
        raise InvalidWindow("Exam window has already ended")

    topics = await question_client.list_topics(authorization=authorization)
    spec = await ai_client.propose_blueprint(
        authorization=authorization,
        candidate_profile_id=candidate_profile_id,
        target_role=target_role,
        seniority_band=seniority_band,
        available_topics=topics,
    )

    topic_mix = [
        TopicMixEntry(
            topic_id=slot.topic_id,
            weight=slot.weight,
            difficulty_min=slot.difficulty_min,
            difficulty_max=slot.difficulty_max,
            question_count=slot.question_count,
        )
        for slot in spec.topic_mix
    ]
    _, version = await blueprints_service.create_blueprint(
        session,
        org_id=org_id,
        name=f"{target_role} ({seniority_band}) — AI-proposed",
        target_role=target_role,
        experience_band=seniority_band,
        total_duration_minutes=spec.total_duration_minutes,
        topic_mix=topic_mix,
    )

    email = candidate_email.strip().lower()
    exam = await exams_repo.create_exam(
        session,
        org_id=org_id,
        blueprint_id=version.blueprint_id,
        blueprint_version_id=version.id,
        candidate_email=email,
        starts_at=starts_at,
        ends_at=ends_at,
        status=ExamStatus.PENDING_GENERATION,
    )
    exam.language_targets = language_targets

    ordinal = 1
    for slot in spec.topic_mix:
        for _ in range(slot.question_count):
            job_id = await ai_client.generate_question(
                authorization=authorization,
                topic_id=slot.topic_id,
                difficulty_band=slot.difficulty_band,
                language_targets=language_targets,
            )
            await slots_repo.create_slot(
                session,
                org_id=org_id,
                exam_id=exam.id,
                ordinal=ordinal,
                topic_id=slot.topic_id,
                difficulty_band=slot.difficulty_band,
                generation_job_id=job_id,
            )
            ordinal += 1

    await session.commit()
    return exam


async def _recompute_exam_status(
    session: AsyncSession, exam: Exam, slots: list[ExamSlotQuestion]
) -> None:
    statuses = {slot.status for slot in slots}
    if SlotStatus.FAILED.value in statuses:
        exam.status = ExamStatus.GENERATION_FAILED
    elif statuses == {SlotStatus.READY.value}:
        exam.status = ExamStatus.PENDING_REVIEW
        exam.review_deadline_at = datetime.now(UTC) + timedelta(
            seconds=get_settings().ai_exam_review_timeout_seconds
        )
    await session.commit()


async def refresh_ai_exam(
    session: AsyncSession,
    exam: Exam,
    *,
    org_id: uuid.UUID,
    ai_client: AiServiceClient,
    redis: Redis,
    email_sender: EmailSender,
    authorization: str,
) -> Exam:
    if exam.status == ExamStatus.PENDING_GENERATION:
        slots = list(
            await slots_repo.list_by_exam(session, org_id=org_id, exam_id=exam.id)
        )
        for slot in slots:
            if slot.status != SlotStatus.PENDING.value:
                continue
            result = await ai_client.get_generation_status(
                authorization=authorization, job_id=slot.generation_job_id
            )
            if result.status == "succeeded":
                slot.question_id = result.question_id
                slot.question_version_id = result.question_version_id
                slot.status = SlotStatus.READY.value
            elif result.status == "failed":
                slot.status = SlotStatus.FAILED.value
                slot.error = result.error
        await _recompute_exam_status(session, exam, slots)

    if (
        exam.status == ExamStatus.PENDING_REVIEW
        and exam.review_deadline_at is not None
        and datetime.now(UTC) >= exam.review_deadline_at
    ):
        await confirm_exam(session, exam, org_id=org_id, redis=redis, email_sender=email_sender)

    return exam


async def confirm_exam(
    session: AsyncSession,
    exam: Exam,
    *,
    org_id: uuid.UUID,
    redis: Redis,
    email_sender: EmailSender,
) -> Exam:
    if exam.status != ExamStatus.PENDING_REVIEW:
        raise InvalidExamStatus(f"Exam is {exam.status.value}, not pending_review")
    await scheduling_service.send_invite(session, redis, email_sender, org_id=org_id, exam=exam)
    exam.status = ExamStatus.SCHEDULED
    await session.commit()
    return exam


async def regenerate_slot(
    session: AsyncSession,
    exam: Exam,
    ordinal: int,
    *,
    org_id: uuid.UUID,
    ai_client: AiServiceClient,
    authorization: str,
) -> ExamSlotQuestion:
    if exam.status not in (
        ExamStatus.PENDING_GENERATION,
        ExamStatus.PENDING_REVIEW,
        ExamStatus.GENERATION_FAILED,
    ):
        raise InvalidExamStatus(f"Exam is {exam.status.value}; slots cannot be regenerated")
    slot = await slots_repo.get_by_ordinal(
        session, org_id=org_id, exam_id=exam.id, ordinal=ordinal
    )
    if slot is None:
        raise NotFound("Slot not found")

    job_id = await ai_client.generate_question(
        authorization=authorization,
        topic_id=slot.topic_id,
        difficulty_band=slot.difficulty_band,
        language_targets=exam.language_targets or [],
    )
    slot.generation_job_id = job_id
    slot.question_id = None
    slot.question_version_id = None
    slot.status = SlotStatus.PENDING.value
    slot.error = None
    exam.status = ExamStatus.PENDING_GENERATION
    exam.review_deadline_at = None
    await session.commit()
    return slot
