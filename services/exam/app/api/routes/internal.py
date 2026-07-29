"""Internal, service-to-service endpoints — NOT exposed through the gateway
(Route("/internal", None, Policy.BLOCKED) at the edge). No examiner auth:
reachable only on the trusted compose network. Exam's first internal route
(it has only ever been an internal *caller* before this) — used by the ai
service's session-evaluation consumer (Phase 2 Slice 7) to fetch a session's
assigned questions and their full submission history, including ordinals
that were assigned but never submitted to. Phase 2 Slice 8 adds the first
internal *write* route: ai's hiring-report consumer pushes the finished
report back here to attach to the session record.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.db.session import get_db
from app.models.examiner import Role
from app.models.submission import Submission
from app.notifications.email import EmailMessage, EmailSender, get_email_sender
from app.repositories import blueprints as blueprints_repo
from app.repositories import examiners as examiners_repo
from app.repositories import exams as exams_repo
from app.repositories import sessions as sessions_repo
from app.repositories import submissions as submissions_repo

router = APIRouter(prefix="/internal", tags=["internal"])

DB = Annotated[AsyncSession, Depends(get_db)]
EmailDep = Annotated[EmailSender, Depends(get_email_sender)]


class InternalSubmission(BaseModel):
    mode: str
    language: str
    source: str
    status: str
    summary_verdict: str | None
    created_at: datetime


class InternalSessionQuestion(BaseModel):
    ordinal: int
    question_id: uuid.UUID
    question_version_id: uuid.UUID
    submissions: list[InternalSubmission]


def _submission(row: Submission) -> InternalSubmission:
    return InternalSubmission(
        mode=row.mode,
        language=row.language,
        source=row.source,
        status=row.status,
        summary_verdict=row.summary_verdict,
        created_at=row.created_at,
    )


@router.get(
    "/sessions/{session_id}/questions",
    response_model=list[InternalSessionQuestion],
)
async def list_session_questions(
    session_id: uuid.UUID, org_id: uuid.UUID, session: DB
) -> list[InternalSessionQuestion]:
    # org_id is still required — multi-tenancy is structural even internally.
    exam_session = await sessions_repo.get_by_id(session, org_id=org_id, session_id=session_id)
    if exam_session is None:
        raise NotFound("Session not found")

    questions = await sessions_repo.list_questions(session, org_id=org_id, session_id=session_id)
    submissions = await submissions_repo.list_by_session(
        session, org_id=org_id, session_id=session_id
    )
    by_ordinal: dict[int, list[Submission]] = defaultdict(list)
    for row in submissions:
        if row.ordinal is not None:
            by_ordinal[row.ordinal].append(row)

    return [
        InternalSessionQuestion(
            ordinal=q.ordinal,
            question_id=q.question_id,
            question_version_id=q.question_version_id,
            submissions=[_submission(row) for row in by_ordinal.get(q.ordinal, [])],
        )
        for q in questions
    ]


class InternalSessionContext(BaseModel):
    candidate_email: str
    target_role: str
    experience_band: str
    candidate_profile_id: uuid.UUID | None


@router.get("/sessions/{session_id}", response_model=InternalSessionContext)
async def get_session_context(
    session_id: uuid.UUID, org_id: uuid.UUID, session: DB
) -> InternalSessionContext:
    exam_session = await sessions_repo.get_by_id(session, org_id=org_id, session_id=session_id)
    if exam_session is None:
        raise NotFound("Session not found")
    exam = await exams_repo.get_by_id(session, org_id=org_id, exam_id=exam_session.exam_id)
    if exam is None:
        raise NotFound("Exam not found")
    version = await blueprints_repo.get_version(
        session, org_id=org_id, version_id=exam.blueprint_version_id
    )
    if version is None:
        raise NotFound("Blueprint version not found")
    return InternalSessionContext(
        candidate_email=exam_session.candidate_email,
        target_role=version.target_role,
        experience_band=version.experience_band,
        candidate_profile_id=exam.candidate_profile_id,
    )


class AttachHiringReportRequest(BaseModel):
    org_id: uuid.UUID
    report_json: dict[str, Any]
    recommendation: str


@router.post("/sessions/{session_id}/report", status_code=204)
async def attach_hiring_report(
    session_id: uuid.UUID, body: AttachHiringReportRequest, session: DB, email_sender: EmailDep
) -> None:
    exam_session = await sessions_repo.get_by_id(
        session, org_id=body.org_id, session_id=session_id
    )
    if exam_session is None:
        raise NotFound("Session not found")

    exam_session.hiring_report_json = body.report_json
    exam_session.hiring_report_recommendation = body.recommendation
    exam_session.hiring_report_generated_at = datetime.now(UTC)
    await session.commit()

    # No exam->examiner addressing exists (examiners are org-wide, exams
    # have no owner) — notify every reviewer/admin in the org.
    examiners = await examiners_repo.list_by_org(session, org_id=body.org_id)
    for examiner in examiners:
        if examiner.role not in (Role.REVIEWER, Role.ADMIN):
            continue
        await email_sender.send(
            EmailMessage(
                to=examiner.email,
                subject="Hiring report ready",
                body=f"A hiring report is ready to review for session {session_id}.",
            )
        )
