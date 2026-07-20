import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound
from app.models.question import Question, QuestionStatus
from app.models.question_version import QuestionVersion
from app.repositories import questions as questions_repo
from app.repositories import test_cases as test_cases_repo
from app.repositories import topics as topics_repo


async def _require_question(
    session: AsyncSession, *, org_id: uuid.UUID, question_id: uuid.UUID
) -> Question:
    question = await questions_repo.get_by_id(
        session, org_id=org_id, question_id=question_id
    )
    if question is None:
        raise NotFound("Question not found")
    return question


async def _current_version(
    session: AsyncSession, question: Question
) -> QuestionVersion:
    assert question.current_version_id is not None
    version = await questions_repo.get_version(
        session, org_id=question.org_id, version_id=question.current_version_id
    )
    assert version is not None
    return version


async def _validate_topics(
    session: AsyncSession, *, org_id: uuid.UUID, topic_ids: Sequence[uuid.UUID]
) -> None:
    found = await topics_repo.get_many(session, org_id=org_id, topic_ids=topic_ids)
    if len(found) != len(set(topic_ids)):
        raise NotFound("One or more topics not found")


async def ensure_mutable_version(
    session: AsyncSession, question: Question
) -> QuestionVersion:
    """Copy-on-write: if the current version is the published one, snapshot a
    new version (fields + test-case metadata) and move the current pointer.
    The published version row is never touched again."""
    current = await _current_version(session, question)
    if question.current_version_id != question.published_version_id:
        return current  # unpublished working copy — mutable in place

    new_version = await questions_repo.create_version(
        session,
        org_id=question.org_id,
        question_id=question.id,
        version_number=current.version_number + 1,
        title=current.title,
        statement_md=current.statement_md,
        constraints_md=current.constraints_md,
        difficulty=current.difficulty,
        time_limit_ms=current.time_limit_ms,
        memory_limit_mb=current.memory_limit_mb,
        starter_code=dict(current.starter_code),
    )
    for tc in await test_cases_repo.list_by_version(
        session, org_id=question.org_id, question_version_id=current.id
    ):
        # S3 objects are shared between versions; keys are immutable uploads.
        await test_cases_repo.create_test_case(
            session,
            org_id=question.org_id,
            question_version_id=new_version.id,
            ordinal=tc.ordinal,
            is_sample=tc.is_sample,
            input_s3_key=tc.input_s3_key,
            expected_output_s3_key=tc.expected_output_s3_key,
        )
    question.current_version_id = new_version.id
    await session.flush()
    return new_version


async def create_question(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    title: str,
    statement_md: str,
    constraints_md: str,
    difficulty: int,
    time_limit_ms: int,
    memory_limit_mb: int,
    starter_code: dict[str, str],
    topic_ids: Sequence[uuid.UUID],
) -> tuple[Question, QuestionVersion, list[uuid.UUID]]:
    await _validate_topics(session, org_id=org_id, topic_ids=topic_ids)
    question = await questions_repo.create_question(session, org_id=org_id)
    version = await questions_repo.create_version(
        session,
        org_id=org_id,
        question_id=question.id,
        version_number=1,
        title=title,
        statement_md=statement_md,
        constraints_md=constraints_md,
        difficulty=difficulty,
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_limit_mb,
        starter_code=starter_code,
    )
    question.current_version_id = version.id
    await questions_repo.set_topics(
        session, question_id=question.id, topic_ids=list(topic_ids)
    )
    await session.commit()
    return question, version, list(topic_ids)


async def get_question_detail(
    session: AsyncSession, *, org_id: uuid.UUID, question_id: uuid.UUID
) -> tuple[Question, QuestionVersion, list[uuid.UUID]]:
    question = await _require_question(session, org_id=org_id, question_id=question_id)
    version = await _current_version(session, question)
    topic_ids = await questions_repo.get_topic_ids(session, question_id=question.id)
    return question, version, topic_ids


async def list_questions(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    topic_id: uuid.UUID | None,
    difficulty: int | None,
    status: QuestionStatus | None,
) -> Sequence[tuple[Question, QuestionVersion]]:
    return await questions_repo.list_by_org(
        session, org_id=org_id, topic_id=topic_id, difficulty=difficulty, status=status
    )


async def update_question(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    question_id: uuid.UUID,
    version_fields: dict[str, object],
    topic_ids: Sequence[uuid.UUID] | None,
) -> tuple[Question, QuestionVersion, list[uuid.UUID]]:
    question = await _require_question(session, org_id=org_id, question_id=question_id)
    if question.status == QuestionStatus.ARCHIVED:
        raise Conflict("Archived questions cannot be edited")

    if version_fields:
        version = await ensure_mutable_version(session, question)
        for field, value in version_fields.items():
            setattr(version, field, value)
    else:
        version = await _current_version(session, question)

    if topic_ids is not None:
        # Topic links live on the question identity, not the version — no
        # copy-on-write needed for a pure topic change.
        await _validate_topics(session, org_id=org_id, topic_ids=topic_ids)
        await questions_repo.set_topics(
            session, question_id=question.id, topic_ids=list(topic_ids)
        )

    await session.commit()
    final_topic_ids = await questions_repo.get_topic_ids(session, question_id=question.id)
    return question, version, final_topic_ids


async def publish_question(
    session: AsyncSession, *, org_id: uuid.UUID, question_id: uuid.UUID
) -> tuple[Question, QuestionVersion, list[uuid.UUID]]:
    question = await _require_question(session, org_id=org_id, question_id=question_id)
    if question.status == QuestionStatus.ARCHIVED:
        raise Conflict("Archived questions cannot be published")
    if question.current_version_id == question.published_version_id:
        raise Conflict("Current version is already published")
    question.published_version_id = question.current_version_id
    question.status = QuestionStatus.PUBLISHED
    await session.commit()
    version = await _current_version(session, question)
    topic_ids = await questions_repo.get_topic_ids(session, question_id=question.id)
    return question, version, topic_ids


async def list_versions(
    session: AsyncSession, *, org_id: uuid.UUID, question_id: uuid.UUID
) -> Sequence[QuestionVersion]:
    await _require_question(session, org_id=org_id, question_id=question_id)
    return await questions_repo.list_versions(
        session, org_id=org_id, question_id=question_id
    )
