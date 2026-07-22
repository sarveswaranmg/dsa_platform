import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EmailMismatch, EmailNotVerified, InviteInvalid
from app.core.redis_keys import invite_key
from app.core.security import create_candidate_exam_token, decode_invite_token
from app.models.exam import Exam
from app.models.invite import InviteStatus
from app.oidc.google import GoogleOIDCVerifier
from app.repositories import exams as exams_repo
from app.repositories import invites as invites_repo


def _normalize(email: str) -> str:
    return email.strip().lower()


async def exchange(
    session: AsyncSession,
    redis: Redis,
    verifier: GoogleOIDCVerifier,
    *,
    invite_token: str,
    google_id_token: str,
) -> tuple[Exam, str]:
    # 1. Signature + window (tampered / expired → InviteInvalid). Not yet
    #    single-use — Redis decides that, and only after the email matches.
    payload = decode_invite_token(invite_token)
    jti = str(payload["jti"])
    invited_email = _normalize(str(payload["candidate_email"]))

    # 2. Authenticate with Google BEFORE consuming, so a mismatch leaves the
    #    token usable by the real candidate.
    identity = await verifier.verify(google_id_token)
    if not identity.email_verified:
        raise EmailNotVerified()
    if _normalize(identity.email) != invited_email:
        raise EmailMismatch()

    # 3. Atomically consume the single-use token. A miss means it was already
    #    used or the window's TTL elapsed.
    consumed = await redis.getdel(invite_key(jti))
    if consumed is None:
        raise InviteInvalid()

    invite = await invites_repo.get_by_id(
        session, invite_id=uuid.UUID(str(payload["invite_id"]))
    )
    exam = await exams_repo.get_by_id(
        session,
        org_id=uuid.UUID(str(payload["org_id"])),
        exam_id=uuid.UUID(str(payload["exam_id"])),
    )
    if invite is None or exam is None:
        raise InviteInvalid()

    invite.status = InviteStatus.CONSUMED
    invite.consumed_at = datetime.now(UTC)
    await session.commit()

    # 4. Issue the exam-scoped candidate token, valid only within the window.
    exam_token = create_candidate_exam_token(
        invite_id=invite.id,
        org_id=exam.org_id,
        exam_id=exam.id,
        blueprint_version_id=exam.blueprint_version_id,
        candidate_email=exam.candidate_email,
        not_before=exam.starts_at,
        expires_at=exam.ends_at,
    )
    return exam, exam_token
