"""Orchestrates the test-case factory (Phase 2 Slice 3): given a
question_version_id produced by a succeeded Slice 2 generation job, draft
candidate test cases, validate them against the stored input_spec, submit
the survivors to judge-gen for differential testing against the stored
reference/brute-force solutions, and attach the agreeing cases to the
question version. See docs/design-testcase-factory.md.

Two variants:
- Async (default): fire-and-forget background task (Slice 1/2 pattern);
  the shared `gen_consumer` finalizes the result when it arrives.
- Synchronous (on-demand, for mid-exam follow-ups): the whole pipeline
  runs inline within the request, bounded by
  `settings.testcase_factory_sync_timeout_seconds`, using a throwaway
  per-request reply queue so it never contends with the persistent
  consumer over the shared async results queue.
"""

import asyncio
import base64
import logging
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.question_service import QuestionServiceClient
from app.core import s3
from app.core.config import get_settings
from app.core.exceptions import NotFound
from app.db.session import get_sessionmaker
from app.generation.schemas import GeneratedQuestionDraft, GeneratedTestCase
from app.generation.validate import validate_input
from app.llm.client import LLMClient
from app.messaging import sqs
from app.messaging.gen_contracts import (
    CompareMode,
    DiffInputRef,
    DiffJob,
    DiffResult,
    DiffStatus,
    Language,
    Limits,
)
from app.messaging.sqs import QueuePublisher
from app.models.generation_job import GenerationJob
from app.models.test_case_generation_job import TestCaseGenerationJob, TestCaseGenerationStatus
from app.repositories import generation_jobs as generation_jobs_repo
from app.repositories import test_case_generation_jobs as test_case_generation_jobs_repo

logger = logging.getLogger("ai.testcase_generation")

# Same asyncio-task-keepalive pattern as app/services/profiles.py and
# app/services/generation.py.
_background_tasks: set[asyncio.Task[None]] = set()


def _track(task: asyncio.Task[None]) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def start_factory_job(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    question_version_id: uuid.UUID,
    synchronous: bool,
    llm_client: LLMClient,
    publisher: QueuePublisher,
    question_client: QuestionServiceClient,
    source_question_id: uuid.UUID | None = None,
) -> TestCaseGenerationJob:
    # Mid-exam follow-up (Phase 2 Slice 6): the copy-on-write draft version
    # has no generation_jobs row of its own — fall back to the latest
    # succeeded job for the underlying question (any version) as the source
    # of the reference/brute-force solution and draft input_spec.
    if source_question_id is not None:
        source_job = await generation_jobs_repo.get_succeeded_by_question(
            session, org_id=org_id, question_id=source_question_id
        )
    else:
        source_job = await generation_jobs_repo.get_succeeded_by_version(
            session, org_id=org_id, question_version_id=question_version_id
        )
    if source_job is None:
        raise NotFound(
            "No succeeded generation job produced this question version — "
            "the test-case factory only supports AI-generated questions"
        )
    # A succeeded generation job always has question_id populated (set at
    # the same time as status=succeeded in finalize_success).
    assert source_job.question_id is not None

    job = await test_case_generation_jobs_repo.create_job(
        session,
        org_id=org_id,
        question_id=source_job.question_id,
        question_version_id=question_version_id,
        generation_job_id=source_job.id,
        synchronous=synchronous,
    )
    await session.commit()

    if synchronous:
        await _run_sync_factory(session, job, source_job, llm_client, publisher, question_client)
    else:
        task = asyncio.create_task(
            _run_async_factory(job.id, org_id, llm_client, publisher)
        )
        _track(task)
    return job


async def _generate_and_validate_candidates(
    draft: GeneratedQuestionDraft,
    llm_client: LLMClient,
    *,
    edge_count: int,
    adversarial_count: int,
    stress_count: int,
) -> list[GeneratedTestCase]:
    candidates = await llm_client.generate_test_cases(
        draft,
        edge_count=edge_count,
        adversarial_count=adversarial_count,
        stress_count=stress_count,
    )
    return [c for c in candidates if not validate_input(c.input, draft.input_spec)]


def _in_network_s3_url(url: str) -> str:
    """Question service's presigned URLs are generated for browser/host
    consumption (its own s3_presign_endpoint_url, e.g. `localhost:4566`) —
    the examiner console PUTs test-case content straight from the browser.
    This finalizer instead PUTs from wherever *this* service is actually
    running, so it swaps in ai's own s3_endpoint_url host:port (already
    correct for either environment — `localstack:4566` in containers,
    `localhost:4566` for tests running on the host) while keeping the
    presigned path/query (the AWS SigV4 signature) untouched."""
    target = urlsplit(get_settings().s3_endpoint_url)
    parsed = urlsplit(url)
    return urlunsplit((target.scheme, target.netloc, parsed.path, parsed.query, parsed.fragment))


def _upload_candidates(
    job_id: uuid.UUID, candidates: list[GeneratedTestCase]
) -> list[DiffInputRef]:
    refs = []
    for ordinal, candidate in enumerate(candidates, start=1):
        key = f"test-cases/{job_id}/input-{ordinal}.txt"
        s3.put_object(key, candidate.input.encode())
        refs.append(DiffInputRef(ordinal=ordinal, input_s3_key=key))
    return refs


def _build_diff_job(
    job: TestCaseGenerationJob,
    source_job: GenerationJob,
    input_refs: list[DiffInputRef],
    *,
    results_queue: str | None = None,
) -> DiffJob:
    assert source_job.reference_solution is not None
    assert source_job.brute_force_solution is not None
    return DiffJob(
        job_id=job.id,
        org_id=job.org_id,
        attempt=1,  # no retry concept for the factory — one differential pass
        language=Language.PYTHON,
        reference_source=source_job.reference_solution,
        brute_force_source=source_job.brute_force_solution,
        limits=Limits(time_ms=2000, memory_mb=256),
        compare_mode=CompareMode.WHITESPACE,
        inputs=input_refs,
        capture_agreement_outputs=True,
        results_queue=results_queue,
    )


async def _run_async_factory(
    job_id: uuid.UUID, org_id: uuid.UUID, llm_client: LLMClient, publisher: QueuePublisher
) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        job = await test_case_generation_jobs_repo.get_by_id(session, org_id=org_id, job_id=job_id)
        if job is None:
            return
        try:
            source_job = await generation_jobs_repo.get_by_id(
                session, org_id=org_id, job_id=job.generation_job_id
            )
            assert source_job is not None and source_job.draft is not None

            job.status = TestCaseGenerationStatus.GENERATING
            await session.commit()

            settings = get_settings()
            draft = GeneratedQuestionDraft.model_validate(source_job.draft)
            candidates = await _generate_and_validate_candidates(
                draft,
                llm_client,
                edge_count=settings.testcase_factory_edge_count,
                adversarial_count=settings.testcase_factory_adversarial_count,
                stress_count=settings.testcase_factory_stress_count,
            )
            if not candidates:
                job.status = TestCaseGenerationStatus.SUCCEEDED
                job.kept_case_count = 0
                await session.commit()
                return

            input_refs = _upload_candidates(job.id, candidates)
            job.status = TestCaseGenerationStatus.VALIDATING
            await session.commit()

            diff_job = _build_diff_job(job, source_job, input_refs)
            publisher.send(settings.gen_jobs_queue, diff_job.model_dump_json())
        except Exception as exc:
            logger.exception("test-case factory drafting failed for %s", job_id)
            await session.rollback()
            job.status = TestCaseGenerationStatus.FAILED
            job.error = str(exc)
            await session.commit()


async def _poll_for_result(queue: str, *, deadline_at: float) -> DiffResult | None:
    while time.monotonic() < deadline_at:
        remaining = deadline_at - time.monotonic()
        wait_seconds = max(1, min(5, int(remaining)))
        messages = await asyncio.to_thread(
            sqs.receive, queue, wait_seconds=wait_seconds, max_messages=1
        )
        for message in messages:
            await asyncio.to_thread(sqs.delete, queue, message["receipt_handle"])
            return DiffResult.model_validate_json(message["body"])
    return None


async def _run_sync_factory(
    session: AsyncSession,
    job: TestCaseGenerationJob,
    source_job: GenerationJob,
    llm_client: LLMClient,
    publisher: QueuePublisher,
    question_client: QuestionServiceClient,
) -> None:
    settings = get_settings()
    deadline_at = time.monotonic() + settings.testcase_factory_sync_timeout_seconds
    reply_queue = f"dsa-judge-gen-sync-{job.id.hex}"
    sqs.queue_url(reply_queue)  # created upfront so the worker can publish to it
    try:
        assert source_job.draft is not None
        job.status = TestCaseGenerationStatus.GENERATING
        await session.commit()

        draft = GeneratedQuestionDraft.model_validate(source_job.draft)
        count = settings.testcase_factory_sync_case_count
        edge_count = count // 3
        adversarial_count = count // 3
        stress_count = count - edge_count - adversarial_count
        candidates = await _generate_and_validate_candidates(
            draft,
            llm_client,
            edge_count=edge_count,
            adversarial_count=adversarial_count,
            stress_count=stress_count,
        )
        if not candidates:
            job.status = TestCaseGenerationStatus.SUCCEEDED
            job.kept_case_count = 0
            await session.commit()
            return

        input_refs = _upload_candidates(job.id, candidates)
        job.status = TestCaseGenerationStatus.VALIDATING
        await session.commit()

        diff_job = _build_diff_job(job, source_job, input_refs, results_queue=reply_queue)
        publisher.send(settings.gen_jobs_queue, diff_job.model_dump_json())

        result = await _poll_for_result(reply_queue, deadline_at=deadline_at)
        if result is None:
            job.status = TestCaseGenerationStatus.FAILED
            job.error = "judge-gen did not respond within the timeout"
            await session.commit()
            return
        await finalize_factory_result(session, job, result, question_client)
    except Exception as exc:
        logger.exception("synchronous test-case factory failed for %s", job.id)
        await session.rollback()
        job.status = TestCaseGenerationStatus.FAILED
        job.error = str(exc)
        await session.commit()
    finally:
        sqs.delete_queue(reply_queue)


async def finalize_factory_result(
    session: AsyncSession,
    job: TestCaseGenerationJob,
    result: DiffResult,
    question_client: QuestionServiceClient,
) -> None:
    if result.status != DiffStatus.COMPLETED:
        job.status = TestCaseGenerationStatus.FAILED
        job.error = result.compile_error or f"diff run failed: {result.status}"
        await session.commit()
        return

    kept = 0
    discarded_cases = []
    for case in result.cases:
        if not case.agree:
            discarded_cases.append(case.model_dump())
            continue
        assert case.reference_output_b64 is not None
        input_key = f"test-cases/{job.id}/input-{case.ordinal}.txt"
        input_bytes = s3.get_object_bytes(input_key)
        output_bytes = base64.b64decode(case.reference_output_b64)

        upload = await question_client.create_test_case_upload(
            org_id=job.org_id, question_id=job.question_id, is_sample=False
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.put(_in_network_s3_url(upload.upload_input_url), content=input_bytes)
            await client.put(_in_network_s3_url(upload.upload_output_url), content=output_bytes)
        kept += 1

    job.status = TestCaseGenerationStatus.SUCCEEDED
    job.kept_case_count = kept
    if discarded_cases:
        job.discard_log = {"cases": discarded_cases}
    await session.commit()
