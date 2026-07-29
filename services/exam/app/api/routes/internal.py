"""Internal, service-to-service endpoints — NOT exposed through the gateway
(Route("/internal", None, Policy.BLOCKED) at the edge). No examiner auth:
reachable only on the trusted compose network. Exam's first internal route
(it has only ever been an internal *caller* before this) — used by the ai
service's session-evaluation consumer (Phase 2 Slice 7) to fetch a session's
assigned questions and their full submission history, including ordinals
that were assigned but never submitted to.
"""

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.db.session import get_db
from app.models.submission import Submission
from app.repositories import sessions as sessions_repo
from app.repositories import submissions as submissions_repo

router = APIRouter(prefix="/internal", tags=["internal"])

DB = Annotated[AsyncSession, Depends(get_db)]


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
