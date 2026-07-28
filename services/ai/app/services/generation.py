"""Orchestrates one generation job: draft (once) -> validate -> [generate
solutions + inputs -> submit to judge-gen] per attempt (max
settings.generation_max_attempts). Retries regenerate only the solutions
and inputs, never the draft — see docs/design-question-generation.md.

The initial draft/first-attempt runs as a detached `asyncio.create_task`
fired right after `POST /questions/generate` commits (same shape as
Slice 1's profile ingestion). Retries are driven synchronously from
`app/services/gen_consumer.py`'s message handler, inside its own
already-open session — judge-gen retries are rare enough (at most 2 per
job) that this doesn't need its own detached task.
"""

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.question_service import QuestionServiceClient
from app.core import s3
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.generation.input_generator import generate_inputs
from app.generation.schemas import GeneratedQuestionDraft
from app.generation.validate import validate_draft
from app.llm.client import LLMClient
from app.messaging.gen_contracts import (
    CompareMode,
    DiffInputRef,
    DiffJob,
    DiffResult,
    Language,
    Limits,
)
from app.messaging.sqs import QueuePublisher
from app.models.generation_job import GenerationJob, GenerationStatus
from app.repositories import generation_jobs as generation_jobs_repo

logger = logging.getLogger("ai.generation")

# asyncio only holds a weak reference to a task's coroutine — keep a strong
# one here (same pattern as app/services/profiles.py's ingestion task).
_background_tasks: set[asyncio.Task[None]] = set()


def _track(task: asyncio.Task[None]) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def start_generation(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    topic_id: uuid.UUID,
    difficulty_band: str,
    language_targets: list[str],
    llm_client: LLMClient,
    publisher: QueuePublisher,
) -> GenerationJob:
    job = await generation_jobs_repo.create_job(
        session,
        org_id=org_id,
        topic_id=topic_id,
        difficulty_band=difficulty_band,
        language_targets=language_targets,
    )
    await session.commit()

    task = asyncio.create_task(_draft_and_start(job.id, org_id, llm_client, publisher))
    _track(task)
    return job


async def _draft_and_start(
    job_id: uuid.UUID, org_id: uuid.UUID, llm_client: LLMClient, publisher: QueuePublisher
) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        job = await generation_jobs_repo.get_by_id(session, org_id=org_id, job_id=job_id)
        if job is None:
            return
        try:
            job.status = GenerationStatus.DRAFTING
            await session.commit()

            # The LLM gets the raw topic_id as context; question service
            # validates the topic actually exists when the question is
            # eventually created (finalize_success below).
            draft = await llm_client.draft_question(
                str(job.topic_id), job.difficulty_band, job.language_targets
            )
            errors = validate_draft(draft, job.difficulty_band, job.language_targets)
            if errors:
                job.status = GenerationStatus.FAILED
                job.error = "; ".join(errors)
                await session.commit()
                return

            job.draft = draft.model_dump()
            job.attempt = 1
            job.status = GenerationStatus.VALIDATING
            await session.commit()

            await _submit_attempt(session, job, llm_client, publisher)
        except Exception as exc:
            logger.exception("generation drafting failed for %s", job_id)
            await session.rollback()
            job.status = GenerationStatus.FAILED
            job.error = str(exc)
            await session.commit()


async def _submit_attempt(
    session: AsyncSession, job: GenerationJob, llm_client: LLMClient, publisher: QueuePublisher
) -> None:
    """Generate fresh solutions + inputs for `job`'s current attempt and
    publish one DiffJob. Caller has already set `job.attempt` and `job.draft`
    and committed."""
    assert job.draft is not None
    draft = GeneratedQuestionDraft.model_validate(job.draft)
    reference = await llm_client.generate_solution(draft, "reference")
    brute_force = await llm_client.generate_solution(draft, "brute_force")

    settings = get_settings()
    inputs_text = generate_inputs(draft.input_spec, settings.generation_input_count)
    input_refs = []
    for ordinal, text in enumerate(inputs_text, start=1):
        key = f"generation/{job.id}/{job.attempt}/input-{ordinal}.txt"
        s3.put_object(key, text.encode())
        input_refs.append(DiffInputRef(ordinal=ordinal, input_s3_key=key))

    job.reference_solution = reference
    job.brute_force_solution = brute_force
    await session.commit()

    diff_job = DiffJob(
        job_id=job.id,
        org_id=job.org_id,
        attempt=job.attempt,
        language=Language.PYTHON,
        reference_source=reference,
        brute_force_source=brute_force,
        limits=Limits(time_ms=2000, memory_mb=256),
        compare_mode=CompareMode.WHITESPACE,
        inputs=input_refs,
    )
    publisher.send(settings.gen_jobs_queue, diff_job.model_dump_json())


async def retry_attempt(
    session: AsyncSession, job: GenerationJob, llm_client: LLMClient, publisher: QueuePublisher
) -> None:
    """Called from the results consumer when agreement was below threshold
    and attempts remain."""
    job.attempt += 1
    await session.commit()
    await _submit_attempt(session, job, llm_client, publisher)


async def finalize_success(
    session: AsyncSession, job: GenerationJob, question_client: QuestionServiceClient
) -> None:
    assert job.draft is not None
    draft = GeneratedQuestionDraft.model_validate(job.draft)
    created = await question_client.create_question(
        org_id=job.org_id,
        title=draft.title,
        statement_md=draft.statement_md,
        constraints_md=draft.constraints_md,
        difficulty=draft.difficulty,
        time_limit_ms=2000,
        memory_limit_mb=256,
        starter_code=draft.starter_code,
        topic_ids=[job.topic_id],
    )
    job.question_id = created.question_id
    job.question_version_id = created.version_id
    job.status = GenerationStatus.SUCCEEDED
    await session.commit()


async def finalize_failure(session: AsyncSession, job: GenerationJob, result: DiffResult) -> None:
    job.status = GenerationStatus.FAILED
    job.discard_log = {
        "attempt": result.attempt,
        "agreement_pct": result.agreement_pct,
        "cases": [case.model_dump() for case in result.cases if not case.agree],
    }
    job.error = result.compile_error or (
        f"agreement {result.agreement_pct:.0%} below threshold after "
        f"{result.attempt} attempt(s)"
    )
    await session.commit()
