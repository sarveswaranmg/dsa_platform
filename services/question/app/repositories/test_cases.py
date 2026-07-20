import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_case import TestCase


async def create_test_case(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    question_version_id: uuid.UUID,
    ordinal: int,
    is_sample: bool,
    input_s3_key: str,
    expected_output_s3_key: str,
) -> TestCase:
    test_case = TestCase(
        org_id=org_id,
        question_version_id=question_version_id,
        ordinal=ordinal,
        is_sample=is_sample,
        input_s3_key=input_s3_key,
        expected_output_s3_key=expected_output_s3_key,
    )
    session.add(test_case)
    await session.flush()
    return test_case


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, test_case_id: uuid.UUID
) -> TestCase | None:
    result = await session.execute(
        select(TestCase).where(TestCase.id == test_case_id, TestCase.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def list_by_version(
    session: AsyncSession, *, org_id: uuid.UUID, question_version_id: uuid.UUID
) -> Sequence[TestCase]:
    result = await session.execute(
        select(TestCase)
        .where(
            TestCase.question_version_id == question_version_id,
            TestCase.org_id == org_id,
        )
        .order_by(TestCase.ordinal)
    )
    return result.scalars().all()


async def get_by_ordinal(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    question_version_id: uuid.UUID,
    ordinal: int,
) -> TestCase | None:
    result = await session.execute(
        select(TestCase).where(
            TestCase.question_version_id == question_version_id,
            TestCase.org_id == org_id,
            TestCase.ordinal == ordinal,
        )
    )
    return result.scalar_one_or_none()


async def max_ordinal(
    session: AsyncSession, *, org_id: uuid.UUID, question_version_id: uuid.UUID
) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(TestCase.ordinal), 0)).where(
            TestCase.question_version_id == question_version_id,
            TestCase.org_id == org_id,
        )
    )
    return int(result.scalar_one())


async def delete_test_case(session: AsyncSession, test_case: TestCase) -> None:
    await session.delete(test_case)
    await session.flush()
