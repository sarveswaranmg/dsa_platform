"""Persistent background consumer for the evaluation-complete queue —
mirrors `services/ai/app/services/session_evaluation_consumer.py`'s shape
exactly (long-poll, process, delete-only-on-success, blocking boto3 calls
pushed to a thread). Tests never start this loop — they call
`process_evaluation_complete` directly.

See docs/design-hiring-report.md for the full report design.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.exam_service import ExamServiceClient, get_exam_client
from app.clients.question_service import QuestionServiceClient, get_question_client
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.llm.client import LLMClient, get_llm_client
from app.messaging import sqs
from app.messaging.eval_contracts import EvaluationCompleteEvent
from app.repositories import hiring_reports as hiring_reports_repo
from app.repositories import profiles as profiles_repo
from app.repositories import session_evaluations as session_evaluations_repo
from app.schemas.hiring_report import HiringReport, HiringReportEvidence

logger = logging.getLogger("ai.hiring_report_consumer")


async def process_evaluation_complete(
    session: AsyncSession,
    body: str,
    *,
    llm_client: LLMClient,
    question_client: QuestionServiceClient,
    exam_client: ExamServiceClient,
) -> None:
    event = EvaluationCompleteEvent.model_validate_json(body)

    rows = await session_evaluations_repo.list_by_session(
        session, org_id=event.org_id, session_id=event.session_id
    )
    questions = await exam_client.list_session_questions(
        org_id=event.org_id, session_id=event.session_id
    )
    verdict_by_ordinal: dict[int, str | None] = {}
    for question in questions:
        submits = [s for s in question.submissions if s.mode == "submit"]
        verdict_by_ordinal[question.ordinal] = submits[-1].summary_verdict if submits else None

    ctx = await exam_client.get_session_context(org_id=event.org_id, session_id=event.session_id)
    profile = None
    if ctx.candidate_profile_id is not None:
        profile = await profiles_repo.get_by_id(
            session, org_id=event.org_id, profile_id=ctx.candidate_profile_id
        )

    evidence = []
    for row in rows:
        content = await question_client.get_version_content(
            org_id=event.org_id, version_id=row.question_version_id
        )
        evidence.append(
            HiringReportEvidence(
                question=content.title,
                verdict=verdict_by_ordinal.get(row.ordinal),
                approach=row.approach,
                complexity=row.complexity,
                partial_score=row.partial_score,
            )
        )

    narrative = await llm_client.synthesize_hiring_report(
        target_role=ctx.target_role,
        experience_band=ctx.experience_band,
        profile=profile,
        evidence=evidence,
    )
    report = HiringReport(**narrative.model_dump(), evidence=evidence)
    report_json = report.model_dump(mode="json")

    await hiring_reports_repo.upsert(
        session,
        org_id=event.org_id,
        session_id=event.session_id,
        report_json=report_json,
        recommendation=report.recommendation,
        score=report.overall_score,
    )
    await session.commit()

    await exam_client.attach_hiring_report(
        org_id=event.org_id,
        session_id=event.session_id,
        report_json=report_json,
        recommendation=report.recommendation,
    )


async def run_hiring_report_consumer(stop: asyncio.Event) -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    llm_client = get_llm_client()
    question_client = get_question_client()
    exam_client = get_exam_client()
    logger.info("hiring-report consumer polling %s", settings.evaluation_complete_queue)
    while not stop.is_set():
        messages = await asyncio.to_thread(
            sqs.receive, settings.evaluation_complete_queue, wait_seconds=5
        )
        for message in messages:
            async with sessionmaker() as session:
                try:
                    await process_evaluation_complete(
                        session,
                        message["body"],
                        llm_client=llm_client,
                        question_client=question_client,
                        exam_client=exam_client,
                    )
                except Exception:
                    logger.exception("failed to process evaluation-complete event; will retry")
                    continue
            await asyncio.to_thread(
                sqs.delete, settings.evaluation_complete_queue, message["receipt_handle"]
            )
