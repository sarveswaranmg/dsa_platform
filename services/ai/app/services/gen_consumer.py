"""Persistent background consumer for the judge-gen results queue — mirrors
`services/exam/app/messaging/consumer.py`'s shape exactly (long-poll,
process, delete-only-on-success, blocking boto3 calls pushed to a thread).
Tests never start this loop — they call `process_gen_result` directly.

Handles two independent job types sharing the one lane: Slice 2's question
generation (`generation_jobs`) and Slice 3's test-case factory
(`test_case_generation_jobs`) — dispatched by trying the factory table
first (shorter-lived, and job_id spaces never collide between the two
independent UUIDv7 tables)."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.question_service import QuestionServiceClient, get_question_client
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.llm.client import LLMClient, get_llm_client
from app.messaging import sqs
from app.messaging.gen_contracts import DiffResult, DiffStatus
from app.messaging.sqs import QueuePublisher, get_publisher
from app.repositories import generation_jobs as generation_jobs_repo
from app.repositories import test_case_generation_jobs as test_case_generation_jobs_repo
from app.services import generation as generation_service
from app.services import testcase_generation as testcase_generation_service

logger = logging.getLogger("ai.gen_consumer")


async def process_gen_result(
    session: AsyncSession,
    body: str,
    *,
    llm_client: LLMClient,
    question_client: QuestionServiceClient,
    publisher: QueuePublisher,
) -> None:
    result = DiffResult.model_validate_json(body)

    testcase_job = await test_case_generation_jobs_repo.get_by_id(
        session, org_id=result.org_id, job_id=result.job_id
    )
    if testcase_job is not None:
        await testcase_generation_service.finalize_factory_result(
            session, testcase_job, result, question_client
        )
        return

    job = await generation_jobs_repo.get_by_id(
        session, org_id=result.org_id, job_id=result.job_id
    )
    if job is None:
        return  # deleted, or a duplicate delivery for a job that's gone
    if job.attempt != result.attempt:
        return  # stale result for an attempt already superseded by a retry

    settings = get_settings()
    if (
        result.status == DiffStatus.COMPLETED
        and result.agreement_pct >= settings.generation_agreement_threshold
    ):
        await generation_service.finalize_success(session, job, question_client)
        return

    if job.attempt < settings.generation_max_attempts:
        await generation_service.retry_attempt(session, job, llm_client, publisher)
    else:
        await generation_service.finalize_failure(session, job, result)


async def run_gen_result_consumer(stop: asyncio.Event) -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    llm_client = get_llm_client()
    question_client = get_question_client()
    publisher = get_publisher()
    logger.info("gen-result consumer polling %s", settings.gen_results_queue)
    while not stop.is_set():
        messages = await asyncio.to_thread(
            sqs.receive, settings.gen_results_queue, wait_seconds=5
        )
        for message in messages:
            async with sessionmaker() as session:
                try:
                    await process_gen_result(
                        session,
                        message["body"],
                        llm_client=llm_client,
                        question_client=question_client,
                        publisher=publisher,
                    )
                except Exception:
                    logger.exception("failed to process gen result; will retry")
                    continue
            await asyncio.to_thread(
                sqs.delete, settings.gen_results_queue, message["receipt_handle"]
            )
