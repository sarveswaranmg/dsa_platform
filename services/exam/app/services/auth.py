from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    EmailTaken,
    InvalidCredentials,
    InvalidTOTP,
    TokenInvalid,
    TOTPNotEnabled,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    generate_totp_secret,
    hash_password,
    hash_refresh_token,
    totp_provisioning_uri,
    verify_password,
    verify_totp,
)
from app.models.examiner import Examiner, Role
from app.repositories import examiners as examiners_repo
from app.repositories import orgs as orgs_repo
from app.repositories import refresh_tokens as refresh_tokens_repo
from app.schemas.auth import RegisterResponse, TokenResponse


async def register(
    session: AsyncSession, *, org_name: str, email: str, password: str
) -> RegisterResponse:
    if await examiners_repo.get_by_email(session, email) is not None:
        raise EmailTaken()
    org = await orgs_repo.create_org(session, name=org_name)
    totp_secret = generate_totp_secret()
    examiner = await examiners_repo.create_examiner(
        session,
        org_id=org.id,
        email=email,
        password_hash=hash_password(password),
        role=Role.ADMIN,
        totp_secret=totp_secret,
    )
    await session.commit()
    return RegisterResponse(
        examiner_id=examiner.id,
        org_id=org.id,
        email=email,
        role=Role.ADMIN,
        totp_secret=totp_secret,
        totp_provisioning_uri=totp_provisioning_uri(totp_secret, email),
    )


async def _authenticate_password(session: AsyncSession, email: str, password: str) -> Examiner:
    examiner = await examiners_repo.get_by_email(session, email)
    if (
        examiner is None
        or not examiner.is_active
        or not verify_password(examiner.password_hash, password)
    ):
        raise InvalidCredentials()
    return examiner


async def verify_totp_enrollment(
    session: AsyncSession, *, email: str, password: str, code: str
) -> None:
    examiner = await _authenticate_password(session, email, password)
    if not verify_totp(examiner.totp_secret, code):
        raise InvalidTOTP()
    examiner.totp_enabled = True
    await session.commit()


async def login(
    session: AsyncSession, *, email: str, password: str, totp_code: str
) -> TokenResponse:
    examiner = await _authenticate_password(session, email, password)
    if not examiner.totp_enabled:
        raise TOTPNotEnabled()
    if not verify_totp(examiner.totp_secret, totp_code):
        raise InvalidTOTP()
    return await _issue_tokens(session, examiner)


async def _issue_tokens(session: AsyncSession, examiner: Examiner) -> TokenResponse:
    settings = get_settings()
    access_token = create_access_token(
        examiner_id=examiner.id, org_id=examiner.org_id, role=examiner.role
    )
    raw_refresh = generate_refresh_token()
    await refresh_tokens_repo.create_refresh_token(
        session,
        examiner_id=examiner.id,
        org_id=examiner.org_id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds),
    )
    await session.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_seconds,
    )


async def refresh(session: AsyncSession, *, refresh_token: str) -> TokenResponse:
    row = await refresh_tokens_repo.get_by_hash(session, hash_refresh_token(refresh_token))
    if row is None:
        raise TokenInvalid()
    if row.revoked_at is not None:
        # Reuse of a rotated token: assume compromise, kill every session.
        await refresh_tokens_repo.revoke_all_for_examiner(session, examiner_id=row.examiner_id)
        await session.commit()
        raise TokenInvalid()
    if row.expires_at <= datetime.now(UTC):
        raise TokenInvalid()
    examiner = await examiners_repo.get_by_id(
        session, org_id=row.org_id, examiner_id=row.examiner_id
    )
    if examiner is None or not examiner.is_active:
        raise TokenInvalid()
    await refresh_tokens_repo.revoke(session, row)
    return await _issue_tokens(session, examiner)


async def logout(session: AsyncSession, *, refresh_token: str) -> None:
    row = await refresh_tokens_repo.get_by_hash(session, hash_refresh_token(refresh_token))
    if row is not None and row.revoked_at is None:
        await refresh_tokens_repo.revoke(session, row)
        await session.commit()
