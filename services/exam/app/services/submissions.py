import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.question_service import QuestionServiceClient
from app.core.config import get_settings
from app.core.exceptions import NotFound
from app.messaging.contracts import JobLimits, SubmissionJob, TestCaseRef
from app.messaging.sqs import QueuePublisher
from app.models.case_verdict import CaseVerdict
from app.models.submission import Submission, SubmissionStatus
from app.repositories import exams as exams_repo
from app.repositories import submissions as submissions_repo

# Phase-1 defaults; per-question limits will flow through in a later slice.
DEFAULT_TIME_MS = 2000
DEFAULT_MEMORY_MB = 256


async def create_and_enqueue(
    session: AsyncSession,
    question_client: QuestionServiceClient,
    publisher: QueuePublisher,
    *,
    org_id: uuid.UUID,
    exam_id: uuid.UUID,
    question_version_id: uuid.UUID,
    language: str,
    source: str,
    compare_mode: str = "whitespace",
) -> Submission:
    exam = await exams_repo.get_by_id(session, org_id=org_id, exam_id=exam_id)
    if exam is None:
        raise NotFound("Exam not found")

    # Resolve test-case S3 keys for the pinned version (internal HTTP call).
    keys = await question_client.list_version_test_cases(
        org_id=org_id, version_id=question_version_id
    )
    if not keys:
        raise NotFound("No test cases for this question version")

    submission = await submissions_repo.create_submission(
        session,
        org_id=org_id,
        exam_id=exam_id,
        question_version_id=question_version_id,
        language=language,
        source=source,
        compare_mode=compare_mode,
        status=SubmissionStatus.QUEUED.value,
    )
    await session.commit()

    job = SubmissionJob(
        submission_id=submission.id,
        org_id=org_id,
        language=language,
        source=source,
        compare_mode=compare_mode,
        limits=JobLimits(time_ms=DEFAULT_TIME_MS, memory_mb=DEFAULT_MEMORY_MB),
        cases=[
            TestCaseRef(
                ordinal=k.ordinal,
                input_s3_key=k.input_s3_key,
                expected_output_s3_key=k.expected_output_s3_key,
            )
            for k in keys
        ],
    )
    publisher.send(get_settings().submissions_queue, job.model_dump_json())
    return submission


async def get_submission_detail(
    session: AsyncSession, *, org_id: uuid.UUID, submission_id: uuid.UUID
) -> tuple[Submission, list[CaseVerdict]]:
    submission = await submissions_repo.get_by_id(
        session, org_id=org_id, submission_id=submission_id
    )
    if submission is None:
        raise NotFound("Submission not found")
    verdicts = await submissions_repo.list_case_verdicts(
        session, org_id=org_id, submission_id=submission_id
    )
    return submission, verdicts
