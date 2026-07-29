import uuid
from datetime import UTC, datetime
from typing import Any

from app.clients.exam_service import AssignedQuestion, SessionContext, SubmissionRecord
from app.clients.question_service import QuestionCreated, TestCaseUpload, VersionContent
from app.db.session import get_sessionmaker
from app.llm.client import get_llm_client
from app.messaging.eval_contracts import EvaluationCompleteEvent, SessionCompleteEvent
from app.repositories import session_evaluations as session_evaluations_repo
from app.services.session_evaluation_consumer import process_session_complete


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, queue: str, body: str) -> None:
        self.sent.append((queue, body))


class FakeQuestionClient:
    def __init__(self) -> None:
        self._versions: dict[uuid.UUID, VersionContent] = {}

    def set_version(self, content: VersionContent) -> None:
        self._versions[content.version_id] = content

    async def get_version_content(
        self, *, org_id: uuid.UUID, version_id: uuid.UUID
    ) -> VersionContent:
        return self._versions[version_id]

    async def create_question(self, **kwargs: Any) -> QuestionCreated:
        raise NotImplementedError

    async def create_test_case_upload(self, **kwargs: Any) -> TestCaseUpload:
        raise NotImplementedError


class FakeExamServiceClient:
    def __init__(self) -> None:
        self._questions: dict[uuid.UUID, list[AssignedQuestion]] = {}

    def set_questions(self, session_id: uuid.UUID, questions: list[AssignedQuestion]) -> None:
        self._questions[session_id] = questions

    async def list_session_questions(
        self, *, org_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[AssignedQuestion]:
        return self._questions[session_id]

    async def get_session_context(self, **kwargs: Any) -> SessionContext:
        raise NotImplementedError

    async def attach_hiring_report(self, **kwargs: Any) -> None:
        raise NotImplementedError


def _content(version_id: uuid.UUID, question_id: uuid.UUID) -> VersionContent:
    return VersionContent(
        version_id=version_id,
        question_id=question_id,
        version_number=1,
        title="Add Two Numbers",
        statement_md="Read a and b, print a+b.",
        constraints_md="1 <= a, b <= 100",
        difficulty=1,
        time_limit_ms=2000,
        memory_limit_mb=256,
        starter_code={"python": "pass\n"},
    )


def _submission(mode: str, verdict: str | None) -> SubmissionRecord:
    return SubmissionRecord(
        mode=mode,
        language="python",
        source="print(1)\n",
        status="completed",
        summary_verdict=verdict,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_two_question_session_upserts_both_and_publishes_complete(
    org_id: uuid.UUID,
) -> None:
    session_id = uuid.uuid4()
    exam_id = uuid.uuid4()
    q1_id, q1_version = uuid.uuid4(), uuid.uuid4()
    q2_id, q2_version = uuid.uuid4(), uuid.uuid4()

    question_client = FakeQuestionClient()
    question_client.set_version(_content(q1_version, q1_id))

    exam_client = FakeExamServiceClient()
    exam_client.set_questions(
        session_id,
        [
            AssignedQuestion(
                ordinal=1,
                question_id=q1_id,
                question_version_id=q1_version,
                submissions=[_submission("submit", "AC")],
            ),
            AssignedQuestion(
                ordinal=2,
                question_id=q2_id,
                question_version_id=q2_version,
                submissions=[],  # assigned but never submitted to
            ),
        ],
    )
    publisher = FakePublisher()
    event = SessionCompleteEvent(org_id=org_id, session_id=session_id, exam_id=exam_id)

    async with get_sessionmaker()() as session:
        await process_session_complete(
            session,
            event.model_dump_json(),
            llm_client=get_llm_client(),
            question_client=question_client,
            exam_client=exam_client,
            publisher=publisher,
        )

    async with get_sessionmaker()() as session:
        rows = await session_evaluations_repo.list_by_session(
            session, org_id=org_id, session_id=session_id
        )
    assert len(rows) == 2
    graded, ungraded = rows[0], rows[1]
    assert graded.ordinal == 1
    assert graded.partial_score == 1.0  # AC
    assert graded.complexity == "O(1)"
    assert ungraded.ordinal == 2
    assert ungraded.partial_score == 0.0
    assert ungraded.complexity is None

    assert len(publisher.sent) == 1
    queue, body = publisher.sent[0]
    assert queue == "dsa-evaluation-complete"
    completed = EvaluationCompleteEvent.model_validate_json(body)
    assert completed.session_id == session_id


async def test_redelivery_does_not_duplicate_rows(org_id: uuid.UUID) -> None:
    session_id = uuid.uuid4()
    q_id, q_version = uuid.uuid4(), uuid.uuid4()

    question_client = FakeQuestionClient()
    question_client.set_version(_content(q_version, q_id))
    exam_client = FakeExamServiceClient()
    exam_client.set_questions(
        session_id,
        [
            AssignedQuestion(
                ordinal=1,
                question_id=q_id,
                question_version_id=q_version,
                submissions=[_submission("submit", "AC")],
            )
        ],
    )
    publisher = FakePublisher()
    event = SessionCompleteEvent(org_id=org_id, session_id=session_id, exam_id=uuid.uuid4())

    for _ in range(2):
        async with get_sessionmaker()() as session:
            await process_session_complete(
                session,
                event.model_dump_json(),
                llm_client=get_llm_client(),
                question_client=question_client,
                exam_client=exam_client,
                publisher=publisher,
            )

    async with get_sessionmaker()() as session:
        rows = await session_evaluations_repo.list_by_session(
            session, org_id=org_id, session_id=session_id
        )
    assert len(rows) == 1  # upsert is idempotent, not a second row
    assert len(publisher.sent) == 2  # completeness re-published each time, harmless
