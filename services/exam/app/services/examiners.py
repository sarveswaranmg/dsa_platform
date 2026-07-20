import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EmailTaken, NotFound
from app.core.security import generate_totp_secret, hash_password, totp_provisioning_uri
from app.models.examiner import Examiner, Role
from app.repositories import examiners as examiners_repo
from app.schemas.examiner import ExaminerCreateResponse


async def create_examiner(
    session: AsyncSession, *, org_id: uuid.UUID, email: str, password: str, role: Role
) -> ExaminerCreateResponse:
    if await examiners_repo.get_by_email(session, email) is not None:
        raise EmailTaken()
    totp_secret = generate_totp_secret()
    examiner = await examiners_repo.create_examiner(
        session,
        org_id=org_id,
        email=email,
        password_hash=hash_password(password),
        role=role,
        totp_secret=totp_secret,
    )
    await session.commit()
    return ExaminerCreateResponse(
        id=examiner.id,
        org_id=examiner.org_id,
        email=examiner.email,
        role=examiner.role,
        totp_enabled=examiner.totp_enabled,
        is_active=examiner.is_active,
        created_at=examiner.created_at,
        totp_secret=totp_secret,
        totp_provisioning_uri=totp_provisioning_uri(totp_secret, email),
    )


async def list_examiners(session: AsyncSession, *, org_id: uuid.UUID) -> Sequence[Examiner]:
    return await examiners_repo.list_by_org(session, org_id=org_id)


async def get_examiner(
    session: AsyncSession, *, org_id: uuid.UUID, examiner_id: uuid.UUID
) -> Examiner:
    examiner = await examiners_repo.get_by_id(session, org_id=org_id, examiner_id=examiner_id)
    if examiner is None:
        raise NotFound()
    return examiner
