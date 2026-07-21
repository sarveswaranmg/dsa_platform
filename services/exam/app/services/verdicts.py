"""Verdict consumer — the system-wide idempotency boundary.

A verdict message is keyed on submission_id. Persisting is idempotent:
per-case rows are upserted ON CONFLICT DO NOTHING (unique submission_id+ordinal)
and the submission transitions to a terminal state only once. A redelivered
job (judge re-runs) or a redelivered verdict both collapse to a no-op.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging.contracts import VerdictMessage, VerdictStatus
from app.models.submission import SubmissionStatus
from app.repositories import submissions as submissions_repo

logger = logging.getLogger("exam.verdicts")

_TERMINAL = {
    SubmissionStatus.COMPLETED.value,
    SubmissionStatus.COMPILE_ERROR.value,
    SubmissionStatus.ERROR.value,
}


async def process_verdict_message(session: AsyncSession, body: str) -> None:
    message = VerdictMessage.model_validate_json(body)
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
