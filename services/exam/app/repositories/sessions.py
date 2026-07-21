import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exam_session import ExamSession
from app.models.session_question import SessionQuestion


async def create_session(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    exam_id: uuid.UUID,
    candidate_email: str,
    started_at: datetime,
    deadline_at: datetime,
) -> ExamSession:
    exam_session = ExamSession(
        org_id=org_id,
        exam_id=exam_id,
        candidate_email=candidate_email,
        started_at=started_at,
        deadline_at=deadline_at,
    )
    session.add(exam_session)
    await session.flush()
    return exam_session


async def get_by_exam(
    session: AsyncSession, *, org_id: uuid.UUID, exam_id: uuid.UUID
) -> ExamSession | None:
    result = await session.execute(
        select(ExamSession).where(
            ExamSession.exam_id == exam_id, ExamSession.org_id == org_id
        )
    )
    return result.scalar_one_or_none()


async def add_question(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    ordinal: int,
    question_id: uuid.UUID,
    question_version_id: uuid.UUID,
) -> None:
    session.add(
        SessionQuestion(
            org_id=org_id,
            session_id=session_id,
            ordinal=ordinal,
            question_id=question_id,
            question_version_id=question_version_id,
        )
    )
    await session.flush()


async def list_questions(
    session: AsyncSession, *, org_id: uuid.UUID, session_id: uuid.UUID
) -> Sequence[SessionQuestion]:
    result = await session.execute(
        select(SessionQuestion)
        .where(
            SessionQuestion.session_id == session_id, SessionQuestion.org_id == org_id
        )
        .order_by(SessionQuestion.ordinal)
    )
    return result.scalars().all()


async def get_question(
    session: AsyncSession, *, org_id: uuid.UUID, session_id: uuid.UUID, ordinal: int
) -> SessionQuestion | None:
    result = await session.execute(
        select(SessionQuestion).where(
            SessionQuestion.session_id == session_id,
            SessionQuestion.org_id == org_id,
            SessionQuestion.ordinal == ordinal,
        )
    )
    return result.scalar_one_or_none()
