import uuid
from collections.abc import Sequence

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question, QuestionStatus, question_topics
from app.models.question_version import QuestionVersion


async def create_question(session: AsyncSession, *, org_id: uuid.UUID) -> Question:
    question = Question(org_id=org_id)
    session.add(question)
    await session.flush()
    return question


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, question_id: uuid.UUID
) -> Question | None:
    result = await session.execute(
        select(Question).where(Question.id == question_id, Question.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def list_by_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    topic_id: uuid.UUID | None = None,
    difficulty: int | None = None,
    status: QuestionStatus | None = None,
) -> Sequence[tuple[Question, QuestionVersion]]:
    stmt = (
        select(Question, QuestionVersion)
        .join(QuestionVersion, Question.current_version_id == QuestionVersion.id)
        .where(Question.org_id == org_id)
        .order_by(Question.created_at)
    )
    if topic_id is not None:
        stmt = stmt.join(
            question_topics, question_topics.c.question_id == Question.id
        ).where(question_topics.c.topic_id == topic_id)
    if difficulty is not None:
        stmt = stmt.where(QuestionVersion.difficulty == difficulty)
    if status is not None:
        stmt = stmt.where(Question.status == status)
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def create_version(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    question_id: uuid.UUID,
    version_number: int,
    title: str,
    statement_md: str,
    constraints_md: str,
    difficulty: int,
    time_limit_ms: int,
    memory_limit_mb: int,
    starter_code: dict[str, str],
) -> QuestionVersion:
    version = QuestionVersion(
        org_id=org_id,
        question_id=question_id,
        version_number=version_number,
        title=title,
        statement_md=statement_md,
        constraints_md=constraints_md,
        difficulty=difficulty,
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_limit_mb,
        starter_code=starter_code,
    )
    session.add(version)
    await session.flush()
    return version


async def get_version(
    session: AsyncSession, *, org_id: uuid.UUID, version_id: uuid.UUID
) -> QuestionVersion | None:
    result = await session.execute(
        select(QuestionVersion).where(
            QuestionVersion.id == version_id, QuestionVersion.org_id == org_id
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    session: AsyncSession, *, org_id: uuid.UUID, question_id: uuid.UUID
) -> Sequence[QuestionVersion]:
    result = await session.execute(
        select(QuestionVersion)
        .where(
            QuestionVersion.question_id == question_id,
            QuestionVersion.org_id == org_id,
        )
        .order_by(QuestionVersion.version_number)
    )
    return result.scalars().all()


async def set_topics(
    session: AsyncSession, *, question_id: uuid.UUID, topic_ids: Sequence[uuid.UUID]
) -> None:
    await session.execute(
        delete(question_topics).where(question_topics.c.question_id == question_id)
    )
    if topic_ids:
        await session.execute(
            insert(question_topics),
            [{"question_id": question_id, "topic_id": tid} for tid in topic_ids],
        )
    await session.flush()


async def get_topic_ids(
    session: AsyncSession, *, question_id: uuid.UUID
) -> list[uuid.UUID]:
    result = await session.execute(
        select(question_topics.c.topic_id).where(
            question_topics.c.question_id == question_id
        )
    )
    return list(result.scalars().all())
