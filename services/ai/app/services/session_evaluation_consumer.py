"""Persistent background consumer for the session-complete queue — mirrors
`services/ai/app/services/gen_consumer.py`'s shape exactly (long-poll,
process, delete-only-on-success, blocking boto3 calls pushed to a thread).
Tests never start this loop — they call `process_session_complete` directly.

See docs/design-ai-evaluation.md for the full evaluation design.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.exam_service import ExamServiceClient, get_exam_client
from app.clients.question_service import QuestionServiceClient, get_question_client
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.evaluation.behavioural import edge_cases_tested, failure_response, runs_before_ac
from app.evaluation.complexity import classify
from app.evaluation.partial_credit import score
from app.llm.client import LLMClient, get_llm_client
from app.messaging import sqs
from app.messaging.eval_contracts import EvaluationCompleteEvent, SessionCompleteEvent
from app.messaging.sqs import QueuePublisher, get_publisher
from app.repositories import session_evaluations as session_evaluations_repo

logger = logging.getLogger("ai.session_evaluation_consumer")


async def process_session_complete(
    session: AsyncSession,
    body: str,
    *,
    llm_client: LLMClient,
    question_client: QuestionServiceClient,
    exam_client: ExamServiceClient,
    publisher: QueuePublisher,
) -> None:
    event = SessionCompleteEvent.model_validate_json(body)
    questions = await exam_client.list_session_questions(
        org_id=event.org_id, session_id=event.session_id
    )

    for question in questions:
        submits = [r for r in question.submissions if r.mode == "submit"]
        if not submits:
            # Assigned but never submitted to — no LLM call needed.
            await session_evaluations_repo.upsert(
                session,
                org_id=event.org_id,
                session_id=event.session_id,
                ordinal=question.ordinal,
                question_id=question.question_id,
                question_version_id=question.question_version_id,
                complexity=None,
                approach=None,
                partial_score=score(
                    None, has_submission=False, approach_correct=False, bug_severity="none"
                ),
                behavioural_signals={},
            )
            continue

        graded = submits[-1]  # the latest submit is the canonical graded attempt
        content = await question_client.get_version_content(
            org_id=event.org_id, version_id=question.question_version_id
        )
        assessment = await llm_client.evaluate_submission(
            statement_md=content.statement_md,
            constraints_md=content.constraints_md,
            language=graded.language,
            source=graded.source,
            verdict=graded.summary_verdict or "",
        )
        await session_evaluations_repo.upsert(
            session,
            org_id=event.org_id,
            session_id=event.session_id,
            ordinal=question.ordinal,
            question_id=question.question_id,
            question_version_id=question.question_version_id,
            complexity=classify(graded.language, graded.source),
            approach=assessment.algorithm_family,
            partial_score=score(
                graded.summary_verdict,
                has_submission=True,
                approach_correct=assessment.approach_correct,
                bug_severity=assessment.bug_severity,
            ),
            behavioural_signals={
                "runs_before_ac": runs_before_ac(question.submissions),
                "tested_edge_cases": edge_cases_tested(question.submissions),
                "failure_response": failure_response(question.submissions),
            },
        )

    await session.commit()

    rows = await session_evaluations_repo.list_by_session(
        session, org_id=event.org_id, session_id=event.session_id
    )
    if len(rows) == len(questions):
        publisher.send(
            get_settings().evaluation_complete_queue,
            EvaluationCompleteEvent(
                org_id=event.org_id, session_id=event.session_id
            ).model_dump_json(),
        )


async def run_session_evaluation_consumer(stop: asyncio.Event) -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    llm_client = get_llm_client()
    question_client = get_question_client()
    exam_client = get_exam_client()
    publisher = get_publisher()
    logger.info("session-evaluation consumer polling %s", settings.session_complete_queue)
    while not stop.is_set():
        messages = await asyncio.to_thread(
            sqs.receive, settings.session_complete_queue, wait_seconds=5
        )
        for message in messages:
            async with sessionmaker() as session:
                try:
                    await process_session_complete(
                        session,
                        message["body"],
                        llm_client=llm_client,
                        question_client=question_client,
                        exam_client=exam_client,
                        publisher=publisher,
                    )
                except Exception:
                    logger.exception("failed to process session-complete event; will retry")
                    continue
            await asyncio.to_thread(
                sqs.delete, settings.session_complete_queue, message["receipt_handle"]
            )
