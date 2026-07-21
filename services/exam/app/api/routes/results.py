"""Examiner-facing results.

Candidate submissions are otherwise only readable with a candidate token; these
endpoints let reviewers/proctors/admins read an exam's submission history and
the code a candidate submitted. Everything is org-scoped — a cross-org read is
a 404, not a 403, so an examiner cannot probe for another org's exam ids.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, require_role
from app.core.exceptions import NotFound
from app.db.session import get_db
from app.models.examiner import Role
from app.repositories import exams as exams_repo
from app.repositories import submissions as submissions_repo
from app.schemas.results import SubmissionDetail, SubmissionSummary
from app.schemas.submission import CaseVerdictResponse

router = APIRouter(tags=["results"])

DB = Annotated[AsyncSession, Depends(get_db)]
# Reviewer grades, proctor monitors, admin sees everything; author is an
# authoring role and is deliberately excluded from candidate results.
ResultsCtx = Annotated[
    AuthContext, Depends(require_role(Role.ADMIN, Role.REVIEWER, Role.PROCTOR))
]


@router.get("/exams/{exam_id}/submissions", response_model=list[SubmissionSummary])
async def list_exam_submissions(
    exam_id: uuid.UUID, ctx: ResultsCtx, session: DB
) -> list[SubmissionSummary]:
    exam = await exams_repo.get_by_id(session, org_id=ctx.org_id, exam_id=exam_id)
    if exam is None:
        raise NotFound("Exam not found")
    rows = await submissions_repo.list_by_exam(
        session, org_id=ctx.org_id, exam_id=exam_id
    )
    return [SubmissionSummary.model_validate(row) for row in rows]


@router.get("/submissions/{submission_id}", response_model=SubmissionDetail)
async def get_submission_detail(
    submission_id: uuid.UUID, ctx: ResultsCtx, session: DB
) -> SubmissionDetail:
    submission = await submissions_repo.get_by_id(
        session, org_id=ctx.org_id, submission_id=submission_id
    )
    if submission is None:
        raise NotFound("Submission not found")
    verdicts = await submissions_repo.list_case_verdicts(
        session, org_id=ctx.org_id, submission_id=submission_id
    )
    return SubmissionDetail(
        id=submission.id,
        exam_id=submission.exam_id,
        session_id=submission.session_id,
        question_version_id=submission.question_version_id,
        language=submission.language,
        mode=submission.mode,
        status=submission.status,
        summary_verdict=submission.summary_verdict,
        compile_error=submission.compile_error,
        source=submission.source,
        created_at=submission.created_at,
        cases=[CaseVerdictResponse.model_validate(v) for v in verdicts],
    )
