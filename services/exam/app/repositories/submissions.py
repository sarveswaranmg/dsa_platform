import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_verdict import CaseVerdict
from app.models.submission import Submission


async def create_submission(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    exam_id: uuid.UUID,
    question_version_id: uuid.UUID,
    language: str,
    source: str,
    compare_mode: str,
    status: str,
    session_id: uuid.UUID | None = None,
    mode: str = "submit",
) -> Submission:
    submission = Submission(
        org_id=org_id,
        exam_id=exam_id,
        session_id=session_id,
        question_version_id=question_version_id,
        language=language,
        source=source,
        compare_mode=compare_mode,
        status=status,
        mode=mode,
    )
    session.add(submission)
    await session.flush()
    return submission


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, submission_id: uuid.UUID
) -> Submission | None:
    result = await session.execute(
        select(Submission).where(
            Submission.id == submission_id, Submission.org_id == org_id
        )
    )
    return result.scalar_one_or_none()


# Verdict lookups intentionally skip org scoping: the verdict consumer is an
# internal queue worker keyed on submission_id (the org is re-checked against
# the submission row it loads).
async def get_by_id_unscoped(
    session: AsyncSession, *, submission_id: uuid.UUID
) -> Submission | None:
    result = await session.execute(
        select(Submission).where(Submission.id == submission_id)
    )
    return result.scalar_one_or_none()


async def upsert_case_verdict(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    submission_id: uuid.UUID,
    ordinal: int,
    verdict: str,
    runtime_ms: int,
    memory_kb: int,
) -> None:
    # ON CONFLICT DO NOTHING keyed on (submission_id, ordinal): re-delivered
    # verdict messages never duplicate rows.
    stmt = (
        insert(CaseVerdict)
        .values(
            org_id=org_id,
            submission_id=submission_id,
            ordinal=ordinal,
            verdict=verdict,
            runtime_ms=runtime_ms,
            memory_kb=memory_kb,
        )
        .on_conflict_do_nothing(index_elements=["submission_id", "ordinal"])
    )
    await session.execute(stmt)


async def list_by_exam(
    session: AsyncSession, *, org_id: uuid.UUID, exam_id: uuid.UUID
) -> list[Submission]:
    result = await session.execute(
        select(Submission)
        .where(Submission.exam_id == exam_id, Submission.org_id == org_id)
        .order_by(Submission.created_at)
    )
    return list(result.scalars().all())


async def list_case_verdicts(
    session: AsyncSession, *, org_id: uuid.UUID, submission_id: uuid.UUID
) -> list[CaseVerdict]:
    result = await session.execute(
        select(CaseVerdict)
        .where(CaseVerdict.submission_id == submission_id, CaseVerdict.org_id == org_id)
        .order_by(CaseVerdict.ordinal)
    )
    return list(result.scalars().all())
