import uuid
from datetime import UTC, datetime
from typing import Any

from app.clients.exam_service import AssignedQuestion, SessionContext, SubmissionRecord
from app.clients.question_service import QuestionCreated, TestCaseUpload, VersionContent
from app.db.session import get_sessionmaker
from app.llm.client import get_llm_client
from app.messaging.eval_contracts import EvaluationCompleteEvent
from app.repositories import hiring_reports as hiring_reports_repo
from app.repositories import session_evaluations as session_evaluations_repo
from app.services.hiring_report_consumer import process_evaluation_complete


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
        self._contexts: dict[uuid.UUID, SessionContext] = {}
        self.attach_calls: list[dict[str, Any]] = []

    def set_questions(self, session_id: uuid.UUID, questions: list[AssignedQuestion]) -> None:
        self._questions[session_id] = questions

    def set_context(self, session_id: uuid.UUID, context: SessionContext) -> None:
        self._contexts[session_id] = context

    async def list_session_questions(
        self, *, org_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[AssignedQuestion]:
        return self._questions[session_id]

    async def get_session_context(
        self, *, org_id: uuid.UUID, session_id: uuid.UUID
    ) -> SessionContext:
        return self._contexts[session_id]

    async def attach_hiring_report(self, **kwargs: Any) -> None:
        self.attach_calls.append(kwargs)


def _content(version_id: uuid.UUID, question_id: uuid.UUID, title: str) -> VersionContent:
    return VersionContent(
        version_id=version_id,
        question_id=question_id,
        version_number=1,
        title=title,
        statement_md="Statement.",
        constraints_md="1 <= n <= 100",
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


async def test_happy_path_builds_evidence_and_pushes_report(org_id: uuid.UUID) -> None:
    session_id = uuid.uuid4()
    q1_id, q1_version = uuid.uuid4(), uuid.uuid4()
    q2_id, q2_version = uuid.uuid4(), uuid.uuid4()

    question_client = FakeQuestionClient()
    question_client.set_version(_content(q1_version, q1_id, "Two Sum"))
    question_client.set_version(_content(q2_version, q2_id, "BFS Shortest Path"))

    exam_client = FakeExamServiceClient()
    exam_client.set_questions(
        session_id,
        [
            AssignedQuestion(
                ordinal=1, question_id=q1_id, question_version_id=q1_version,
                submissions=[_submission("submit", "AC")],
            ),
            AssignedQuestion(
                ordinal=2, question_id=q2_id, question_version_id=q2_version,
                submissions=[_submission("submit", "WA")],
            ),
        ],
    )
    exam_client.set_context(
        session_id,
        SessionContext(
            candidate_email="cand@example.com", target_role="Backend Engineer",
            experience_band="senior", candidate_profile_id=None,
        ),
    )

    async with get_sessionmaker()() as session:
        await session_evaluations_repo.upsert(
            session, org_id=org_id, session_id=session_id, ordinal=1,
            question_id=q1_id, question_version_id=q1_version,
            complexity="O(n)", approach="hashmap", partial_score=1.0,
            behavioural_signals={},
        )
        await session_evaluations_repo.upsert(
            session, org_id=org_id, session_id=session_id, ordinal=2,
            question_id=q2_id, question_version_id=q2_version,
            complexity="O(n^2)", approach="brute force", partial_score=0.1,
            behavioural_signals={},
        )
        await session.commit()

    event = EvaluationCompleteEvent(org_id=org_id, session_id=session_id)
    async with get_sessionmaker()() as session:
        await process_evaluation_complete(
            session,
            event.model_dump_json(),
            llm_client=get_llm_client(),
            question_client=question_client,
            exam_client=exam_client,
        )

    assert len(exam_client.attach_calls) == 1
    call = exam_client.attach_calls[0]
    assert call["session_id"] == session_id
    report_json = call["report_json"]
    assert report_json["recommendation"] == "maybe"  # mean(1.0, 0.1) = 0.55 -> maybe band
    evidence = report_json["evidence"]
    assert [e["question"] for e in evidence] == ["Two Sum", "BFS Shortest Path"]
    assert evidence[0]["verdict"] == "AC"
    assert evidence[1]["verdict"] == "WA"

    async with get_sessionmaker()() as session:
        stored = await hiring_reports_repo.get_by_session_id(
            session, org_id=org_id, session_id=session_id
        )
    assert stored is not None
    assert stored.recommendation == "maybe"
    assert stored.report_json == report_json


async def test_no_candidate_profile_still_produces_a_report(org_id: uuid.UUID) -> None:
    session_id = uuid.uuid4()
    q_id, q_version = uuid.uuid4(), uuid.uuid4()

    question_client = FakeQuestionClient()
    question_client.set_version(_content(q_version, q_id, "Two Sum"))
    exam_client = FakeExamServiceClient()
    exam_client.set_questions(
        session_id,
        [
            AssignedQuestion(
                ordinal=1, question_id=q_id, question_version_id=q_version,
                submissions=[_submission("submit", "AC")],
            )
        ],
    )
    exam_client.set_context(
        session_id,
        SessionContext(
            candidate_email="cand@example.com", target_role="Backend Engineer",
            experience_band="senior", candidate_profile_id=None,
        ),
    )

    async with get_sessionmaker()() as session:
        await session_evaluations_repo.upsert(
            session, org_id=org_id, session_id=session_id, ordinal=1,
            question_id=q_id, question_version_id=q_version,
            complexity="O(n)", approach="hashmap", partial_score=1.0,
            behavioural_signals={},
        )
        await session.commit()

    event = EvaluationCompleteEvent(org_id=org_id, session_id=session_id)
    async with get_sessionmaker()() as session:
        await process_evaluation_complete(
            session,
            event.model_dump_json(),
            llm_client=get_llm_client(),
            question_client=question_client,
            exam_client=exam_client,
        )

    assert len(exam_client.attach_calls) == 1
    assert exam_client.attach_calls[0]["report_json"]["seniority_match"] == "senior"


async def test_redelivery_updates_in_place_no_duplicate_row(org_id: uuid.UUID) -> None:
    session_id = uuid.uuid4()
    q_id, q_version = uuid.uuid4(), uuid.uuid4()

    question_client = FakeQuestionClient()
    question_client.set_version(_content(q_version, q_id, "Two Sum"))
    exam_client = FakeExamServiceClient()
    exam_client.set_questions(
        session_id,
        [
            AssignedQuestion(
                ordinal=1, question_id=q_id, question_version_id=q_version,
                submissions=[_submission("submit", "AC")],
            )
        ],
    )
    exam_client.set_context(
        session_id,
        SessionContext(
            candidate_email="cand@example.com", target_role="Backend Engineer",
            experience_band="senior", candidate_profile_id=None,
        ),
    )

    async with get_sessionmaker()() as session:
        await session_evaluations_repo.upsert(
            session, org_id=org_id, session_id=session_id, ordinal=1,
            question_id=q_id, question_version_id=q_version,
            complexity="O(n)", approach="hashmap", partial_score=1.0,
            behavioural_signals={},
        )
        await session.commit()

    event = EvaluationCompleteEvent(org_id=org_id, session_id=session_id)
    for _ in range(2):
        async with get_sessionmaker()() as session:
            await process_evaluation_complete(
                session,
                event.model_dump_json(),
                llm_client=get_llm_client(),
                question_client=question_client,
                exam_client=exam_client,
            )

    assert len(exam_client.attach_calls) == 2  # called each time, harmless

    async with get_sessionmaker()() as session:
        stored = await hiring_reports_repo.get_by_session_id(
            session, org_id=org_id, session_id=session_id
        )
    assert stored is not None  # upsert kept it to one row, not duplicated
