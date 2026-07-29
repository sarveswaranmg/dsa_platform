import asyncio
import time
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.clients.question_service import (
    QuestionCreated,
    TestCaseUpload,
    VersionContent,
    get_question_client,
)
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.generation.schemas import (
    DIFFICULTY_BANDS,
    GeneratedExample,
    GeneratedQuestionDraft,
    InputVar,
)
from app.llm.client import get_llm_client
from app.messaging.gen_contracts import DiffCaseResult, DiffJob, DiffResult, DiffStatus, Verdict
from app.messaging.sqs import get_publisher
from app.services.gen_consumer import process_gen_result


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, queue: str, body: str) -> None:
        self.sent.append((queue, body))

    def last_diff_job(self) -> DiffJob:
        return DiffJob.model_validate_json(self.sent[-1][1])


class FakeQuestionClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_question(self, **kwargs: Any) -> QuestionCreated:
        self.calls.append(kwargs)
        return QuestionCreated(
            question_id=uuid.uuid4(), version_id=uuid.uuid4(), version_number=1
        )

    async def create_test_case_upload(self, **kwargs: Any) -> TestCaseUpload:
        raise NotImplementedError  # not exercised by Slice 2's tests

    async def get_version_content(self, **kwargs: Any) -> VersionContent:
        raise NotImplementedError  # not exercised by Slice 2's tests


class BadDraftLLMClient:
    """Drafts a question whose difficulty violates the requested band —
    exercises the "static validation rejects a bad draft" path without ever
    reaching the judge."""

    async def draft_question(
        self, topic: str, difficulty_band: str, language_targets: list[str]
    ) -> GeneratedQuestionDraft:
        _lo, hi = DIFFICULTY_BANDS[difficulty_band]
        return GeneratedQuestionDraft(
            title="Bad",
            statement_md="...",
            constraints_md="",
            examples=[GeneratedExample(input="1", output="1")],
            starter_code={lang: "x" for lang in language_targets},
            input_spec=[InputVar(name="n", kind="int")],
            difficulty=hi + 1,  # out of band on purpose
        )

    async def generate_solution(self, draft: GeneratedQuestionDraft, role: str) -> str:
        raise AssertionError("should never be called — draft is rejected first")

    async def extract_profile(self, resume_text: str, github_signals: object) -> object:
        raise NotImplementedError


@pytest.fixture
def fake_publisher(app: FastAPI) -> FakePublisher:
    publisher = FakePublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return publisher


@pytest.fixture
def fake_question_client(app: FastAPI) -> FakeQuestionClient:
    fake = FakeQuestionClient()
    app.dependency_overrides[get_question_client] = lambda: fake
    return fake


@pytest.fixture(autouse=True)
def small_input_count(monkeypatch: pytest.MonkeyPatch) -> None:
    # 100 real S3 puts per attempt would make this suite painfully slow.
    monkeypatch.setattr(get_settings(), "generation_input_count", 3)


async def _wait_for_status(
    client: AsyncClient,
    headers: dict[str, str],
    job_id: str,
    statuses: set[str],
    timeout: float = 5.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = await client.get(f"/questions/generate/{job_id}", headers=headers)
        assert response.status_code == 200
        body: dict[str, Any] = response.json()
        if body["status"] in statuses:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {statuses}")


async def _wait_until(condition: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never became true")


def _request_body(topic_id: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "topic_id": str(topic_id or uuid.uuid4()),
        "difficulty_band": "easy",
        "language_targets": ["python"],
    }


async def test_create_generation_drafts_and_submits_first_diff_job(
    client: AsyncClient, author: dict[str, str], fake_publisher: FakePublisher, s3_bucket: None
) -> None:
    response = await client.post("/questions/generate", headers=author, json=_request_body())
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]

    body = await _wait_for_status(client, author, job_id, {"validating", "failed"})
    assert body["status"] == "validating"
    # Status flips to "validating" slightly before the DiffJob is actually
    # published (a couple of mocked LLM/S3 awaits happen in between).
    await _wait_until(lambda: len(fake_publisher.sent) >= 1)
    assert body["attempt"] == 1
    assert len(fake_publisher.sent) == 1
    diff_job = fake_publisher.last_diff_job()
    assert str(diff_job.job_id) == job_id
    assert diff_job.attempt == 1
    assert len(diff_job.inputs) == 3  # small_input_count override


async def test_bad_draft_fails_without_ever_submitting_to_judge(
    client: AsyncClient, app: FastAPI, author: dict[str, str], fake_publisher: FakePublisher
) -> None:
    app.dependency_overrides[get_llm_client] = lambda: BadDraftLLMClient()
    response = await client.post("/questions/generate", headers=author, json=_request_body())
    job_id = response.json()["id"]

    body = await _wait_for_status(client, author, job_id, {"failed"})
    assert "difficulty" in body["error"]
    assert fake_publisher.sent == []


async def test_retry_then_success_creates_a_question(
    client: AsyncClient,
    author: dict[str, str],
    org_id: uuid.UUID,
    fake_publisher: FakePublisher,
    fake_question_client: FakeQuestionClient,
    s3_bucket: None,
) -> None:
    create = await client.post("/questions/generate", headers=author, json=_request_body())
    job_id = create.json()["id"]
    await _wait_for_status(client, author, job_id, {"validating"})
    await _wait_until(lambda: len(fake_publisher.sent) >= 1)

    # Attempt 1 disagrees below threshold -> should retry.
    diff_job_1 = fake_publisher.last_diff_job()
    disagreement = DiffResult(
        job_id=diff_job_1.job_id,
        org_id=org_id,
        attempt=1,
        status=DiffStatus.COMPLETED,
        agreement_pct=0.5,
        cases=[
            DiffCaseResult(
                ordinal=1,
                agree=False,
                reference_verdict=Verdict.AC,
                brute_force_verdict=Verdict.WA,
            )
        ],
    )
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await process_gen_result(
            session,
            disagreement.model_dump_json(),
            llm_client=get_llm_client(),
            question_client=fake_question_client,
            publisher=fake_publisher,
        )

    body = await _wait_for_status(client, author, job_id, {"validating"})
    assert body["attempt"] == 2
    assert len(fake_publisher.sent) == 2  # retried: a second DiffJob published

    # Attempt 2 agrees fully -> should succeed and create a question.
    diff_job_2 = fake_publisher.last_diff_job()
    assert diff_job_2.attempt == 2
    agreement = DiffResult(
        job_id=diff_job_2.job_id,
        org_id=org_id,
        attempt=2,
        status=DiffStatus.COMPLETED,
        agreement_pct=1.0,
        cases=[],
    )
    async with sessionmaker() as session:
        await process_gen_result(
            session,
            agreement.model_dump_json(),
            llm_client=get_llm_client(),
            question_client=fake_question_client,
            publisher=fake_publisher,
        )

    body = await _wait_for_status(client, author, job_id, {"succeeded"})
    assert body["question_id"] is not None
    assert body["question_version_id"] is not None
    assert len(fake_question_client.calls) == 1


async def test_exhausting_all_attempts_marks_job_failed(
    client: AsyncClient,
    author: dict[str, str],
    org_id: uuid.UUID,
    fake_publisher: FakePublisher,
    fake_question_client: FakeQuestionClient,
    s3_bucket: None,
) -> None:
    create = await client.post("/questions/generate", headers=author, json=_request_body())
    job_id = create.json()["id"]
    await _wait_for_status(client, author, job_id, {"validating"})
    await _wait_until(lambda: len(fake_publisher.sent) >= 1)

    sessionmaker = get_sessionmaker()
    for expected_attempt in (1, 2, 3):
        diff_job = fake_publisher.last_diff_job()
        assert diff_job.attempt == expected_attempt
        disagreement = DiffResult(
            job_id=diff_job.job_id,
            org_id=org_id,
            attempt=expected_attempt,
            status=DiffStatus.COMPLETED,
            agreement_pct=0.0,
            cases=[
                DiffCaseResult(
                    ordinal=1,
                    agree=False,
                    reference_verdict=Verdict.AC,
                    brute_force_verdict=Verdict.WA,
                    reference_output_b64="YQ==",
                    brute_force_output_b64="Yg==",
                )
            ],
        )
        async with sessionmaker() as session:
            await process_gen_result(
                session,
                disagreement.model_dump_json(),
                llm_client=get_llm_client(),
                question_client=fake_question_client,
                publisher=fake_publisher,
            )

    body = await _wait_for_status(client, author, job_id, {"failed"})
    assert body["question_id"] is None
    assert fake_question_client.calls == []
    assert body["discard_log"]["attempt"] == 3
    assert len(body["discard_log"]["cases"]) == 1
    # Only 3 DiffJobs were ever published — no 4th attempt after exhaustion.
    assert len(fake_publisher.sent) == 3


async def test_exact_threshold_boundary_succeeds(
    client: AsyncClient,
    author: dict[str, str],
    org_id: uuid.UUID,
    fake_publisher: FakePublisher,
    fake_question_client: FakeQuestionClient,
    s3_bucket: None,
) -> None:
    create = await client.post("/questions/generate", headers=author, json=_request_body())
    job_id = create.json()["id"]
    await _wait_for_status(client, author, job_id, {"validating"})
    await _wait_until(lambda: len(fake_publisher.sent) >= 1)

    diff_job = fake_publisher.last_diff_job()
    exactly_at_threshold = DiffResult(
        job_id=diff_job.job_id,
        org_id=org_id,
        attempt=1,
        status=DiffStatus.COMPLETED,
        agreement_pct=get_settings().generation_agreement_threshold,
        cases=[],
    )
    async with get_sessionmaker()() as session:
        await process_gen_result(
            session,
            exactly_at_threshold.model_dump_json(),
            llm_client=get_llm_client(),
            question_client=fake_question_client,
            publisher=fake_publisher,
        )

    body = await _wait_for_status(client, author, job_id, {"succeeded"})
    assert body["status"] == "succeeded"


async def test_reviewer_cannot_create_generation_jobs(
    client: AsyncClient, reviewer: dict[str, str]
) -> None:
    response = await client.post("/questions/generate", headers=reviewer, json=_request_body())
    assert response.status_code == 403


async def test_missing_token_rejected(client: AsyncClient) -> None:
    response = await client.get(f"/questions/generate/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_unknown_or_other_org_job_is_404(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    response = await client.get(f"/questions/generate/{uuid.uuid4()}", headers=author)
    assert response.status_code == 404

    create = await client.post("/questions/generate", headers=author, json=_request_body())
    job_id = create.json()["id"]

    response = await client.get(f"/questions/generate/{job_id}", headers=other_org_author)
    assert response.status_code == 404
