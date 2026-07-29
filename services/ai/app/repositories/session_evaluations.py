import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session_evaluation import SessionEvaluation


async def upsert(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    ordinal: int,
    question_id: uuid.UUID,
    question_version_id: uuid.UUID,
    complexity: str | None,
    approach: str | None,
    partial_score: float,
    behavioural_signals: dict[str, Any],
) -> None:
    # ON CONFLICT DO NOTHING keyed on (session_id, ordinal): re-delivered
    # session-complete events never duplicate rows.
    stmt = (
        insert(SessionEvaluation)
        .values(
            org_id=org_id,
            session_id=session_id,
            ordinal=ordinal,
            question_id=question_id,
            question_version_id=question_version_id,
            complexity=complexity,
            approach=approach,
            partial_score=partial_score,
            behavioural_signals=behavioural_signals,
        )
        .on_conflict_do_nothing(index_elements=["session_id", "ordinal"])
    )
    await session.execute(stmt)


async def list_by_session(
    session: AsyncSession, *, org_id: uuid.UUID, session_id: uuid.UUID
) -> list[SessionEvaluation]:
    result = await session.execute(
        select(SessionEvaluation)
        .where(SessionEvaluation.session_id == session_id, SessionEvaluation.org_id == org_id)
        .order_by(SessionEvaluation.ordinal)
    )
    return list(result.scalars().all())
