import asyncio
import base64
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
from app.core import s3
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.generation.schemas import GeneratedQuestionDraft, GeneratedTestCase
from app.llm.client import MockLLMClient, get_llm_client
from app.messaging.gen_contracts import DiffCaseResult, DiffJob, DiffResult, DiffStatus, Verdict
from app.messaging.sqs import SqsPublisher, get_publisher
from app.services.gen_consumer import process_gen_result


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, queue: str, body: str) -> None:
        self.sent.append((queue, body))

    def last_diff_job(self) -> DiffJob:
        return DiffJob.model_validate_json(self.sent[-1][1])


class SyncSimulatingPublisher:
    """Simulates the judge-gen worker responding instantly: publishes a
    canned agreeing DiffResult straight to the job's throwaway reply queue
    (real localstack SQS) — used to test the on-demand variant's real poll
    loop without a real judge worker."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, queue: str, body: str) -> None:
        self.sent.append((queue, body))
        diff_job = DiffJob.model_validate_json(body)
        assert diff_job.results_queue is not None
        result = DiffResult(
            job_id=diff_job.job_id,
            org_id=diff_job.org_id,
            attempt=diff_job.attempt,
            status=DiffStatus.COMPLETED,
            agreement_pct=1.0,
            cases=[
                DiffCaseResult(
                    ordinal=ref.ordinal,
                    agree=True,
                    reference_verdict=Verdict.AC,
                    brute_force_verdict=Verdict.AC,
                    reference_output_b64=base64.b64encode(b"5\n").decode(),
                )
                for ref in diff_job.inputs
            ],
        )
        SqsPublisher().send(diff_job.results_queue, result.model_dump_json())


class SucceedingQuestionClient:
    """Minimal fake for the Slice 2 setup phase — only create_question is
    exercised there."""

    async def create_question(self, **kwargs: Any) -> QuestionCreated:
        return QuestionCreated(question_id=uuid.uuid4(), version_id=uuid.uuid4(), version_number=1)

    async def create_test_case_upload(self, **kwargs: Any) -> TestCaseUpload:
        raise NotImplementedError

    async def get_version_content(self, **kwargs: Any) -> VersionContent:
        raise NotImplementedError


class FakeQuestionClientForFactory:
    """Returns real presigned PUT URLs against ai's own bucket (not
    question service's) — enough to prove finalize_factory_result actually
    uploads the kept cases' content, without needing question service
    running at all."""

    def __init__(self) -> None:
        self.uploads: list[dict[str, str]] = []

    async def create_question(self, **kwargs: Any) -> QuestionCreated:
        raise NotImplementedError

    async def create_test_case_upload(self, **kwargs: Any) -> TestCaseUpload:
        test_case_id = uuid.uuid4()
        input_key = f"test/{test_case_id}/input"
        output_key = f"test/{test_case_id}/output"
        self.uploads.append({"input_key": input_key, "output_key": output_key})
        return TestCaseUpload(
            id=test_case_id,
            ordinal=len(self.uploads),
            upload_input_url=s3.presign_put(input_key),
            upload_output_url=s3.presign_put(output_key),
        )

    async def get_version_content(self, **kwargs: Any) -> VersionContent:
        raise NotImplementedError


class PartiallyInvalidLLMClient(MockLLMClient):
    """One valid candidate, one that violates the draft's bounds —
    exercises validate_input rejecting a candidate before it ever reaches
    judge."""

    async def generate_test_cases(
        self,
        draft: GeneratedQuestionDraft,
        *,
        edge_count: int,
        adversarial_count: int,
        stress_count: int,
    ) -> list[GeneratedTestCase]:
        return [
            GeneratedTestCase(input="500\n500", description="valid", case_type="edge"),
            GeneratedTestCase(input="99999\n1", description="out of bounds", case_type="edge"),
        ]


async def _wait_for_status(
    client: AsyncClient,
    headers: dict[str, str],
    path: str,
    statuses: set[str],
    timeout: float = 5.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = await client.get(path, headers=headers)
        assert response.status_code == 200
        body: dict[str, Any] = response.json()
        if body["status"] in statuses:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(f"{path} never reached {statuses}")


async def _wait_until(condition: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never became true")


async def _create_succeeded_generation_job(
    app: FastAPI, client: AsyncClient, headers: dict[str, str], org_id: uuid.UUID
) -> uuid.UUID:
    """Drives a Slice 2 generation job to `succeeded` — the test-case
    factory's only supported input — and returns its question_version_id."""
    setup_publisher = FakePublisher()
    app.dependency_overrides[get_publisher] = lambda: setup_publisher
    app.dependency_overrides[get_question_client] = lambda: SucceedingQuestionClient()

    create = await client.post(
        "/questions/generate",
        headers=headers,
        json={
            "topic_id": str(uuid.uuid4()),
            "difficulty_band": "easy",
            "language_targets": ["python"],
        },
    )
    job_id = create.json()["id"]
    await _wait_for_status(client, headers, f"/questions/generate/{job_id}", {"validating"})
    await _wait_until(lambda: len(setup_publisher.sent) >= 1)

    diff_job = DiffJob.model_validate_json(setup_publisher.sent[-1][1])
    agreement = DiffResult(
        job_id=diff_job.job_id,
        org_id=org_id,
        attempt=1,
        status=DiffStatus.COMPLETED,
        agreement_pct=1.0,
        cases=[],
    )
    async with get_sessionmaker()() as session:
        await process_gen_result(
            session,
            agreement.model_dump_json(),
            llm_client=get_llm_client(),
            question_client=SucceedingQuestionClient(),
            publisher=setup_publisher,
        )
    body = await _wait_for_status(client, headers, f"/questions/generate/{job_id}", {"succeeded"})
    return uuid.UUID(body["question_version_id"])


async def test_rejects_version_with_no_succeeded_generation_job(
    client: AsyncClient, author: dict[str, str]
) -> None:
    response = await client.post(
        "/test-cases/generate",
        headers=author,
        json={"question_version_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


async def test_invalid_candidates_are_dropped_before_reaching_judge(
    app: FastAPI,
    client: AsyncClient,
    author: dict[str, str],
    org_id: uuid.UUID,
    s3_bucket: None,
) -> None:
    version_id = await _create_succeeded_generation_job(app, client, author, org_id)

    factory_publisher = FakePublisher()
    app.dependency_overrides[get_publisher] = lambda: factory_publisher
    app.dependency_overrides[get_llm_client] = lambda: PartiallyInvalidLLMClient()
    app.dependency_overrides[get_question_client] = lambda: FakeQuestionClientForFactory()

    response = await client.post(
        "/test-cases/generate", headers=author, json={"question_version_id": str(version_id)}
    )
    assert response.status_code == 201
    await _wait_until(lambda: len(factory_publisher.sent) >= 1)

    diff_job = factory_publisher.last_diff_job()
    assert len(diff_job.inputs) == 1  # only the valid candidate survived


async def test_kept_and_discarded_cases_are_recorded(
    app: FastAPI,
    client: AsyncClient,
    author: dict[str, str],
    org_id: uuid.UUID,
    s3_bucket: None,
) -> None:
    version_id = await _create_succeeded_generation_job(app, client, author, org_id)

    factory_publisher = FakePublisher()
    fake_question_client = FakeQuestionClientForFactory()
    app.dependency_overrides[get_publisher] = lambda: factory_publisher
    app.dependency_overrides[get_llm_client] = lambda: MockLLMClient()
    app.dependency_overrides[get_question_client] = lambda: fake_question_client

    response = await client.post(
        "/test-cases/generate", headers=author, json={"question_version_id": str(version_id)}
    )
    job_id = response.json()["id"]
    await _wait_until(lambda: len(factory_publisher.sent) >= 1)
    diff_job = factory_publisher.last_diff_job()
    assert len(diff_job.inputs) == 30  # default 10 edge + 10 adversarial + 10 stress

    cases = []
    for i, ref in enumerate(diff_job.inputs, start=1):
        agree = i % 2 == 0
        cases.append(
            DiffCaseResult(
                ordinal=ref.ordinal,
                agree=agree,
                reference_verdict=Verdict.AC,
                brute_force_verdict=Verdict.AC if agree else Verdict.WA,
                reference_output_b64=(
                    base64.b64encode(f"out-{i}\n".encode()).decode() if agree else None
                ),
                brute_force_output_b64=(None if agree else base64.b64encode(b"wrong\n").decode()),
            )
        )
    result = DiffResult(
        job_id=diff_job.job_id,
        org_id=org_id,
        attempt=1,
        status=DiffStatus.COMPLETED,
        agreement_pct=0.5,
        cases=cases,
    )
    async with get_sessionmaker()() as session:
        await process_gen_result(
            session,
            result.model_dump_json(),
            llm_client=get_llm_client(),
            question_client=fake_question_client,
            publisher=factory_publisher,
        )

    body = await _wait_for_status(
        client, author, f"/test-cases/generate/{job_id}", {"succeeded", "failed"}
    )
    assert body["status"] == "succeeded"
    assert body["kept_case_count"] == 15
    assert len(body["discard_log"]["cases"]) == 15
    assert len(fake_question_client.uploads) == 15
    # Kept content genuinely landed in S3.
    uploaded = fake_question_client.uploads[0]
    assert s3.get_object_bytes(uploaded["output_key"]).startswith(b"out-")


async def test_synchronous_variant_completes_inline(
    app: FastAPI,
    client: AsyncClient,
    author: dict[str, str],
    org_id: uuid.UUID,
    s3_bucket: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_id = await _create_succeeded_generation_job(app, client, author, org_id)

    fake_question_client = FakeQuestionClientForFactory()
    app.dependency_overrides[get_publisher] = lambda: SyncSimulatingPublisher()
    app.dependency_overrides[get_llm_client] = lambda: MockLLMClient()
    app.dependency_overrides[get_question_client] = lambda: fake_question_client
    monkeypatch.setattr(get_settings(), "testcase_factory_sync_case_count", 3)

    response = await client.post(
        "/test-cases/generate",
        headers=author,
        json={"question_version_id": str(version_id), "synchronous": True},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "succeeded"  # the whole pipeline ran inline

    detail = await client.get(f"/test-cases/generate/{body['id']}", headers=author)
    assert detail.json()["kept_case_count"] == 3
    assert len(fake_question_client.uploads) == 3


async def test_synchronous_variant_times_out_if_judge_gen_never_responds(
    app: FastAPI,
    client: AsyncClient,
    author: dict[str, str],
    org_id: uuid.UUID,
    s3_bucket: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_id = await _create_succeeded_generation_job(app, client, author, org_id)

    app.dependency_overrides[get_publisher] = lambda: FakePublisher()  # never replies
    app.dependency_overrides[get_llm_client] = lambda: MockLLMClient()
    app.dependency_overrides[get_question_client] = lambda: FakeQuestionClientForFactory()
    monkeypatch.setattr(get_settings(), "testcase_factory_sync_timeout_seconds", 0.5)
    monkeypatch.setattr(get_settings(), "testcase_factory_sync_case_count", 1)

    response = await client.post(
        "/test-cases/generate",
        headers=author,
        json={"question_version_id": str(version_id), "synchronous": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"


async def test_reviewer_cannot_create_testcase_generation(
    client: AsyncClient, reviewer: dict[str, str]
) -> None:
    response = await client.post(
        "/test-cases/generate", headers=reviewer, json={"question_version_id": str(uuid.uuid4())}
    )
    assert response.status_code == 403


async def test_missing_token_rejected(client: AsyncClient) -> None:
    response = await client.get(f"/test-cases/generate/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_unknown_or_other_org_job_is_404(
    app: FastAPI,
    client: AsyncClient,
    author: dict[str, str],
    other_org_author: dict[str, str],
    org_id: uuid.UUID,
    s3_bucket: None,
) -> None:
    response = await client.get(f"/test-cases/generate/{uuid.uuid4()}", headers=author)
    assert response.status_code == 404

    version_id = await _create_succeeded_generation_job(app, client, author, org_id)
    app.dependency_overrides[get_publisher] = lambda: FakePublisher()
    app.dependency_overrides[get_llm_client] = lambda: MockLLMClient()
    app.dependency_overrides[get_question_client] = lambda: FakeQuestionClientForFactory()
    create = await client.post(
        "/test-cases/generate", headers=author, json={"question_version_id": str(version_id)}
    )
    job_id = create.json()["id"]

    response = await client.get(f"/test-cases/generate/{job_id}", headers=other_org_author)
    assert response.status_code == 404
