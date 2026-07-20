import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import s3
from app.core.exceptions import Conflict, NotFound
from app.models.question import Question, QuestionStatus
from app.models.test_case import TestCase
from app.repositories import questions as questions_repo
from app.repositories import test_cases as test_cases_repo
from app.services.questions import ensure_mutable_version


async def _require_question(
    session: AsyncSession, *, org_id: uuid.UUID, question_id: uuid.UUID
) -> Question:
    question = await questions_repo.get_by_id(
        session, org_id=org_id, question_id=question_id
    )
    if question is None:
        raise NotFound("Question not found")
    if question.status == QuestionStatus.ARCHIVED:
        raise Conflict("Archived questions cannot be edited")
    return question


def _s3_key(
    *,
    org_id: uuid.UUID,
    question_id: uuid.UUID,
    version_number: int,
    test_case_id: uuid.UUID,
    kind: str,
) -> str:
    return f"{org_id}/{question_id}/v{version_number}/{test_case_id}/{kind}"


async def create_test_case(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    question_id: uuid.UUID,
    ordinal: int | None,
    is_sample: bool,
) -> tuple[TestCase, str, str]:
    """Returns (row, presigned_input_put_url, presigned_output_put_url)."""
    question = await _require_question(session, org_id=org_id, question_id=question_id)
    version = await ensure_mutable_version(session, question)

    if ordinal is None:
        ordinal = (
            await test_cases_repo.max_ordinal(
                session, org_id=org_id, question_version_id=version.id
            )
            + 1
        )
    elif await test_cases_repo.get_by_ordinal(
        session, org_id=org_id, question_version_id=version.id, ordinal=ordinal
    ):
        raise Conflict(f"Ordinal {ordinal} already exists on this version")

    test_case_id = uuid.uuid4()
    input_key = _s3_key(
        org_id=org_id,
        question_id=question_id,
        version_number=version.version_number,
        test_case_id=test_case_id,
        kind="input",
    )
    output_key = _s3_key(
        org_id=org_id,
        question_id=question_id,
        version_number=version.version_number,
        test_case_id=test_case_id,
        kind="output",
    )
    test_case = await test_cases_repo.create_test_case(
        session,
        org_id=org_id,
        question_version_id=version.id,
        ordinal=ordinal,
        is_sample=is_sample,
        input_s3_key=input_key,
        expected_output_s3_key=output_key,
    )
    await session.commit()
    return test_case, s3.presign_put(input_key), s3.presign_put(output_key)


async def list_test_cases(
    session: AsyncSession, *, org_id: uuid.UUID, question_id: uuid.UUID
) -> list[tuple[TestCase, str, str]]:
    """Returns (row, presigned_input_get_url, presigned_output_get_url) for
    the question's current version."""
    question = await questions_repo.get_by_id(
        session, org_id=org_id, question_id=question_id
    )
    if question is None or question.current_version_id is None:
        raise NotFound("Question not found")
    rows = await test_cases_repo.list_by_version(
        session, org_id=org_id, question_version_id=question.current_version_id
    )
    return [
        (tc, s3.presign_get(tc.input_s3_key), s3.presign_get(tc.expected_output_s3_key))
        for tc in rows
    ]


async def delete_test_case(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    question_id: uuid.UUID,
    test_case_id: uuid.UUID,
) -> None:
    question = await _require_question(session, org_id=org_id, question_id=question_id)
    test_case = await test_cases_repo.get_by_id(
        session, org_id=org_id, test_case_id=test_case_id
    )
    if test_case is None or test_case.question_version_id != question.current_version_id:
        raise NotFound("Test case not found on the current version")

    version = await ensure_mutable_version(session, question)
    if version.id != test_case.question_version_id:
        # Copy-on-write happened: the row to delete is the copy on the new
        # version, found by its (stable) ordinal.
        copied = await test_cases_repo.get_by_ordinal(
            session,
            org_id=org_id,
            question_version_id=version.id,
            ordinal=test_case.ordinal,
        )
        assert copied is not None
        test_case = copied
    # Metadata delete only — S3 objects may be shared with published
    # versions and are cleaned up out of band (later phase).
    await test_cases_repo.delete_test_case(session, test_case)
    await session.commit()
