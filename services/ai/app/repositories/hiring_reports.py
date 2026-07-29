import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hiring_report import HiringReport


async def upsert(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    report_json: dict[str, Any],
    recommendation: str,
    score: float,
) -> None:
    # ON CONFLICT DO UPDATE keyed on session_id: a redelivered
    # evaluation-complete event (or a non-deterministic real LLM backend)
    # must keep this row and exam's cached columns in agreement, not drift.
    stmt = (
        insert(HiringReport)
        .values(
            org_id=org_id,
            session_id=session_id,
            report_json=report_json,
            recommendation=recommendation,
            score=score,
        )
        .on_conflict_do_update(
            index_elements=["session_id"],
            set_={
                "report_json": report_json,
                "recommendation": recommendation,
                "score": score,
            },
        )
    )
    await session.execute(stmt)


async def get_by_session_id(
    session: AsyncSession, *, org_id: uuid.UUID, session_id: uuid.UUID
) -> HiringReport | None:
    result = await session.execute(
        select(HiringReport).where(
            HiringReport.session_id == session_id, HiringReport.org_id == org_id
        )
    )
    return result.scalar_one_or_none()
