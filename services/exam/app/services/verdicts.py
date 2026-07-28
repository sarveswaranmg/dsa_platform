"""Verdict consumer — the system-wide idempotency boundary.

A verdict message is keyed on submission_id. Persisting is idempotent:
per-case rows are upserted ON CONFLICT DO NOTHING (unique submission_id+ordinal)
and the submission transitions to a terminal state only once. A redelivered
job (judge re-runs) or a redelivered verdict both collapse to a no-op.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ai_service import AiServiceClient
from app.core.logging import set_request_id
from app.messaging.contracts import VerdictMessage, VerdictStatus
from app.models.submission import Submission, SubmissionMode, SubmissionStatus
from app.repositories import sessions as sessions_repo
from app.repositories import submissions as submissions_repo

logger = logging.getLogger("exam.verdicts")

_TERMINAL = {
    SubmissionStatus.COMPLETED.value,
    SubmissionStatus.COMPILE_ERROR.value,
    SubmissionStatus.ERROR.value,
}


async def process_verdict_message(
    session: AsyncSession, body: str, *, ai_client: AiServiceClient
) -> None:
    message = VerdictMessage.model_validate_json(body)
    if message.request_id:
        # Re-bind the originating trace id so this persist log line joins the
        # gateway/exam/judge lines for the same submission.
        set_request_id(message.request_id)
    submission = await submissions_repo.get_by_id_unscoped(
        session, submission_id=message.submission_id
    )
    if submission is None:
        logger.warning("verdict for unknown submission %s; dropping", message.submission_id)
        return
    if submission.org_id != message.org_id:
        logger.error("verdict org mismatch for submission %s; dropping", message.submission_id)
        return
    if submission.status in _TERMINAL:
        return  # already persisted — duplicate delivery

    for case in message.cases:
        await submissions_repo.upsert_case_verdict(
            session,
            org_id=submission.org_id,
            submission_id=submission.id,
            ordinal=case.ordinal,
            verdict=case.verdict,
            runtime_ms=case.runtime_ms,
            memory_kb=case.memory_kb,
        )

    if message.status == VerdictStatus.COMPILE_ERROR:
        submission.status = SubmissionStatus.COMPILE_ERROR.value
        submission.compile_error = message.compile_error
    else:
        submission.status = SubmissionStatus.COMPLETED.value
    submission.summary_verdict = message.summary_verdict
    await session.commit()

    if submission.mode == SubmissionMode.SUBMIT.value and submission.session_id is not None:
        await _signal_difficulty(session, submission, message, ai_client=ai_client)


async def _signal_difficulty(
    session: AsyncSession,
    submission: Submission,
    message: VerdictMessage,
    *,
    ai_client: AiServiceClient,
) -> None:
    """Adaptive difficulty engine (Phase 2 Slice 5) — observability only:
    records the engine's updated band on the session, doesn't yet change
    what question the candidate sees next. Never allowed to break verdict
    persistence, which has already committed by the time this runs."""
    assert submission.session_id is not None  # caller already checked
    try:
        exam_session = await sessions_repo.get_by_id(
            session, org_id=submission.org_id, session_id=submission.session_id
        )
        if exam_session is None:
            return
        assigned = await sessions_repo.get_question_by_version(
            session,
            org_id=submission.org_id,
            session_id=submission.session_id,
            question_version_id=submission.question_version_id,
        )
        if assigned is None or assigned.shown_at is None:
            return

        questions = await sessions_repo.list_questions(
            session, org_id=submission.org_id, session_id=submission.session_id
        )
        allotted_seconds = (
            exam_session.deadline_at - exam_session.started_at
        ).total_seconds() / len(questions)
        elapsed_seconds = (datetime.now(UTC) - assigned.shown_at).total_seconds()
        time_elapsed_pct = elapsed_seconds / allotted_seconds

        result = await ai_client.send_difficulty_signal(
            session_id=submission.session_id,
            question_version_id=submission.question_version_id,
            time_elapsed_pct=time_elapsed_pct,
            verdict=message.summary_verdict,
            complexity_hint=None,  # no complexity detector exists yet (Slice 7)
        )
        exam_session.current_difficulty = result.difficulty
        exam_session.current_difficulty_band = result.difficulty_band
        await session.commit()
    except Exception:
        logger.exception(
            "difficulty signal failed for submission %s; continuing", submission.id
        )
