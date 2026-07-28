import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.clients.question_service import get_question_client
from app.db.session import get_sessionmaker
from app.llm.client import MockLLMClient, get_llm_client
from app.messaging.gen_contracts import DiffJob, DiffResult, DiffStatus
from app.messaging.sqs import get_publisher
from app.repositories import generation_jobs as generation_jobs_repo
from app.services.gen_consumer import process_gen_result
from tests.test_testcase_generation import (
    FakePublisher,
    FakeQuestionClientForFactory,
    SucceedingQuestionClient,
    SyncSimulatingPublisher,
    _wait_for_status,
    _wait_until,
)


async def _create_succeeded_generation_job(
    app: FastAPI, client: AsyncClient, headers: dict[str, str], org_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """Same flow as test_testcase_generation.py's helper, but also returns
    question_id (needed for the lineage lookup)."""
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
    return uuid.UUID(body["question_id"]), uuid.UUID(body["question_version_id"])


async def test_get_succeeded_by_question_finds_latest_across_versions(
    app: FastAPI, client: AsyncClient, author: dict[str, str], org_id: uuid.UUID
) -> None:
    question_id, version_id = await _create_succeeded_generation_job(app, client, author, org_id)

    async with get_sessionmaker()() as session:
        found = await generation_jobs_repo.get_succeeded_by_question(
            session, org_id=org_id, question_id=question_id
        )
    assert found is not None
    assert found.question_version_id == version_id


async def test_get_succeeded_by_question_none_when_no_lineage(
    org_id: uuid.UUID,
) -> None:
    async with get_sessionmaker()() as session:
        found = await generation_jobs_repo.get_succeeded_by_question(
            session, org_id=org_id, question_id=uuid.uuid4()
        )
    assert found is None


async def test_internal_generate_uses_lineage_and_requires_no_auth(
    app: FastAPI,
    client: AsyncClient,
    author: dict[str, str],
    org_id: uuid.UUID,
    s3_bucket: None,
) -> None:
    question_id, _original_version_id = await _create_succeeded_generation_job(
        app, client, author, org_id
    )
    new_draft_version_id = uuid.uuid4()  # a follow-up's forked version

    fake_question_client = FakeQuestionClientForFactory()
    app.dependency_overrides[get_publisher] = lambda: SyncSimulatingPublisher()
    app.dependency_overrides[get_llm_client] = lambda: MockLLMClient()
    app.dependency_overrides[get_question_client] = lambda: fake_question_client

    response = await client.post(
        "/internal/test-cases/generate",
        json={
            "org_id": str(org_id),
            "question_version_id": str(new_draft_version_id),
            "source_question_id": str(question_id),
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "succeeded"  # ran inline, no auth needed
    assert len(fake_question_client.uploads) > 0


async def test_internal_generate_404s_with_no_lineage(
    client: AsyncClient, org_id: uuid.UUID
) -> None:
    response = await client.post(
        "/internal/test-cases/generate",
        json={
            "org_id": str(org_id),
            "question_version_id": str(uuid.uuid4()),
            "source_question_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404
