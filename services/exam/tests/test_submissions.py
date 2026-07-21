import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.question_service import (
    PublishedQuestionRef,
    QuestionRef,
    TestCaseKeys,
    VersionContent,
)
from app.messaging.contracts import (
    CaseResult,
    SubmissionJob,
    VerdictMessage,
    VerdictStatus,
)
from app.models.submission import SubmissionStatus
from app.repositories import blueprints as blueprints_repo
from app.repositories import exams as exams_repo
from app.repositories import submissions as submissions_repo
from app.services import submissions as submissions_service
from app.services.verdicts import process_verdict_message


class FakeQuestionClient:
    def __init__(self, keys: list[TestCaseKeys]) -> None:
        self.keys = keys

    async def list_published_questions(self, **kwargs: object) -> list[QuestionRef]:
        return []

    async def list_version_test_cases(
        self, *, org_id: uuid.UUID, version_id: uuid.UUID
    ) -> list[TestCaseKeys]:
        return self.keys

    async def list_published_questions_internal(
        self, *, org_id: uuid.UUID, topic_id: uuid.UUID, difficulty: int
    ) -> list[PublishedQuestionRef]:
        raise NotImplementedError

    async def get_version_content(
        self, *, org_id: uuid.UUID, version_id: uuid.UUID
    ) -> VersionContent:
        raise NotImplementedError


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, queue: str, body: str) -> None:
        self.sent.append((queue, body))


async def _make_exam(session: AsyncSession, org_id: uuid.UUID) -> uuid.UUID:
    blueprint = await blueprints_repo.create_blueprint(session, org_id=org_id, name="BP")
    version = await blueprints_repo.create_version(
        session,
        org_id=org_id,
        blueprint_id=blueprint.id,
        version_number=1,
        target_role="BE",
        experience_band="senior",
        total_duration_minutes=90,
        topic_mix=[],
    )
    blueprint.current_version_id = version.id
    now = datetime.now(UTC)
    exam = await exams_repo.create_exam(
        session,
        org_id=org_id,
        blueprint_id=blueprint.id,
        blueprint_version_id=version.id,
        candidate_email="c@example.com",
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(hours=1),
    )
    await session.commit()
    return exam.id


_KEYS = [
    TestCaseKeys(ordinal=1, input_s3_key="k/1/in", expected_output_s3_key="k/1/out"),
    TestCaseKeys(ordinal=2, input_s3_key="k/2/in", expected_output_s3_key="k/2/out"),
]


async def test_enqueue_builds_correct_job(db_session: AsyncSession) -> None:
    org_id = uuid.uuid4()
    exam_id = await _make_exam(db_session, org_id)
    version_id = uuid.uuid4()
    publisher = FakePublisher()

    submission = await submissions_service.create_and_enqueue(
        db_session,
        FakeQuestionClient(_KEYS),
        publisher,
        org_id=org_id,
        exam_id=exam_id,
        question_version_id=version_id,
        language="python",
        source="print(1)\n",
    )
    assert submission.status == SubmissionStatus.QUEUED.value

    assert len(publisher.sent) == 1
    queue, body = publisher.sent[0]
    assert queue == "dsa-submissions"
    job = SubmissionJob.model_validate_json(body)
    assert job.submission_id == submission.id
    assert job.org_id == org_id
    assert job.language == "python"
    assert [c.ordinal for c in job.cases] == [1, 2]
    assert job.cases[0].input_s3_key == "k/1/in"


async def test_enqueue_rejects_missing_exam(db_session: AsyncSession) -> None:
    from app.core.exceptions import NotFound

    publisher = FakePublisher()
    try:
        await submissions_service.create_and_enqueue(
            db_session,
            FakeQuestionClient(_KEYS),
            publisher,
            org_id=uuid.uuid4(),
            exam_id=uuid.uuid4(),
            question_version_id=uuid.uuid4(),
            language="python",
            source="x",
        )
        raise AssertionError("expected NotFound")
    except NotFound:
        pass
    assert publisher.sent == []


async def test_verdict_persistence_and_idempotency(db_session: AsyncSession) -> None:
    org_id = uuid.uuid4()
    exam_id = await _make_exam(db_session, org_id)
    submission = await submissions_service.create_and_enqueue(
        db_session,
        FakeQuestionClient(_KEYS),
        FakePublisher(),
        org_id=org_id,
        exam_id=exam_id,
        question_version_id=uuid.uuid4(),
        language="python",
        source="x",
    )

    message = VerdictMessage(
        submission_id=submission.id,
        org_id=org_id,
        status=VerdictStatus.COMPLETED,
        summary_verdict="AC",
        cases=[
            CaseResult(ordinal=1, verdict="AC", runtime_ms=12, memory_kb=1000),
            CaseResult(ordinal=2, verdict="AC", runtime_ms=15, memory_kb=1100),
        ],
    )

    await process_verdict_message(db_session, message.model_dump_json())
    reloaded = await submissions_repo.get_by_id(
        db_session, org_id=org_id, submission_id=submission.id
    )
    assert reloaded is not None
    assert reloaded.status == SubmissionStatus.COMPLETED.value
    assert reloaded.summary_verdict == "AC"
    verdicts = await submissions_repo.list_case_verdicts(
        db_session, org_id=org_id, submission_id=submission.id
    )
    assert [v.ordinal for v in verdicts] == [1, 2]

    # Re-deliver the same verdict: no duplicate rows, still terminal.
    await process_verdict_message(db_session, message.model_dump_json())
    verdicts_again = await submissions_repo.list_case_verdicts(
        db_session, org_id=org_id, submission_id=submission.id
    )
    assert len(verdicts_again) == 2


async def test_compile_error_verdict(db_session: AsyncSession) -> None:
    org_id = uuid.uuid4()
    exam_id = await _make_exam(db_session, org_id)
    submission = await submissions_service.create_and_enqueue(
        db_session,
        FakeQuestionClient(_KEYS),
        FakePublisher(),
        org_id=org_id,
        exam_id=exam_id,
        question_version_id=uuid.uuid4(),
        language="cpp",
        source="bad",
    )
    message = VerdictMessage(
        submission_id=submission.id,
        org_id=org_id,
        status=VerdictStatus.COMPILE_ERROR,
        summary_verdict="CE",
        compile_error="error: expected ';'",
        cases=[],
    )
    await process_verdict_message(db_session, message.model_dump_json())
    reloaded = await submissions_repo.get_by_id(
        db_session, org_id=org_id, submission_id=submission.id
    )
    assert reloaded is not None
    assert reloaded.status == SubmissionStatus.COMPILE_ERROR.value
    assert reloaded.compile_error and "expected" in reloaded.compile_error


async def test_verdict_org_mismatch_dropped(db_session: AsyncSession) -> None:
    org_id = uuid.uuid4()
    exam_id = await _make_exam(db_session, org_id)
    submission = await submissions_service.create_and_enqueue(
        db_session,
        FakeQuestionClient(_KEYS),
        FakePublisher(),
        org_id=org_id,
        exam_id=exam_id,
        question_version_id=uuid.uuid4(),
        language="python",
        source="x",
    )
    # A verdict claiming a different org for this submission must not persist.
    message = VerdictMessage(
        submission_id=submission.id,
        org_id=uuid.uuid4(),
        status=VerdictStatus.COMPLETED,
        summary_verdict="AC",
        cases=[CaseResult(ordinal=1, verdict="AC", runtime_ms=1, memory_kb=1)],
    )
    await process_verdict_message(db_session, message.model_dump_json())
    reloaded = await submissions_repo.get_by_id(
        db_session, org_id=org_id, submission_id=submission.id
    )
    assert reloaded is not None
    assert reloaded.status == SubmissionStatus.QUEUED.value  # unchanged
