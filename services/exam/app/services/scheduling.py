import json
import secrets
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import InvalidWindow, NotFound
from app.core.redis_keys import invite_key
from app.core.security import create_invite_token
from app.models.exam import Exam
from app.models.invite import Invite
from app.notifications.email import EmailMessage, EmailSender
from app.repositories import exams as exams_repo
from app.repositories import invites as invites_repo
from app.services import blueprints as blueprints_service


def invite_link(token: str) -> str:
    return f"{get_settings().frontend_base_url}/exam/invite?token={token}"


async def schedule_exam(
    session: AsyncSession,
    redis: Redis,
    email_sender: EmailSender,
    *,
    org_id: uuid.UUID,
    candidate_email: str,
    blueprint_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
) -> tuple[Exam, Invite, str]:
    now = datetime.now(UTC)
    if ends_at <= now:
        raise InvalidWindow("Exam window has already ended")

    # Resolve + pin the blueprint's current version (org-scoped; raises
    # NotFound for a missing or cross-org blueprint).
    _, version = await blueprints_service.get_blueprint(
        session, org_id=org_id, blueprint_id=blueprint_id
    )

    email = candidate_email.strip().lower()
    exam = await exams_repo.create_exam(
        session,
        org_id=org_id,
        blueprint_id=blueprint_id,
        blueprint_version_id=version.id,
        candidate_email=email,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    jti = secrets.token_urlsafe(32)
    invite = await invites_repo.create_invite(
        session, org_id=org_id, exam_id=exam.id, jti=jti, candidate_email=email
    )

    token = create_invite_token(
        jti=jti,
        invite_id=invite.id,
        exam_id=exam.id,
        org_id=org_id,
        candidate_email=email,
        not_before=now,
        expires_at=ends_at,
    )
    # Redis is the single-use authority; TTL retires the key when the window ends.
    ttl = max(1, int((ends_at - now).total_seconds()))
    await redis.set(
        invite_key(jti),
        json.dumps({"invite_id": str(invite.id), "exam_id": str(exam.id)}),
        ex=ttl,
    )
    await session.commit()

    link = invite_link(token)
    await email_sender.send(
        EmailMessage(
            to=email,
            subject="Your DSA exam invitation",
            body=(
                "You have been invited to a DSA assessment. Open this "
                f"single-use link to begin:\n\n{link}\n\n"
                f"The exam window is {starts_at.isoformat()} to {ends_at.isoformat()}."
            ),
        )
    )
    return exam, invite, link


async def list_exams(session: AsyncSession, *, org_id: uuid.UUID) -> list[Exam]:
    return list(await exams_repo.list_by_org(session, org_id=org_id))


async def get_exam_with_invite(
    session: AsyncSession, *, org_id: uuid.UUID, exam_id: uuid.UUID
) -> tuple[Exam, Invite | None]:
    exam = await exams_repo.get_by_id(session, org_id=org_id, exam_id=exam_id)
    if exam is None:
        raise NotFound("Exam not found")
    invite = await invites_repo.get_for_exam(session, org_id=org_id, exam_id=exam_id)
    return exam, invite
