import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import Forbidden, TokenInvalid
from app.core.security import decode_access_token, decode_candidate_exam_token
from app.models.examiner import Role

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    examiner_id: uuid.UUID
    org_id: uuid.UUID
    role: Role


@dataclass(frozen=True)
class CandidateContext:
    invite_id: uuid.UUID
    org_id: uuid.UUID
    exam_id: uuid.UUID
    blueprint_version_id: uuid.UUID
    candidate_email: str


async def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> AuthContext:
    if credentials is None:
        raise TokenInvalid()
    payload = decode_access_token(credentials.credentials)
    try:
        return AuthContext(
            examiner_id=uuid.UUID(payload["sub"]),
            org_id=uuid.UUID(payload["org_id"]),
            role=Role(payload["role"]),
        )
    except (ValueError, KeyError) as exc:
        raise TokenInvalid() from exc


async def get_candidate_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> CandidateContext:
    if credentials is None:
        raise TokenInvalid()
    payload = decode_candidate_exam_token(credentials.credentials)
    try:
        return CandidateContext(
            invite_id=uuid.UUID(payload["sub"]),
            org_id=uuid.UUID(payload["org_id"]),
            exam_id=uuid.UUID(payload["exam_id"]),
            blueprint_version_id=uuid.UUID(payload["blueprint_version_id"]),
            candidate_email=str(payload["candidate_email"]),
        )
    except (ValueError, KeyError) as exc:
        raise TokenInvalid() from exc


def require_role(*roles: Role) -> Callable[..., Coroutine[Any, Any, AuthContext]]:
    """Dependency factory: any authenticated examiner if no roles given,
    otherwise only the listed roles."""

    async def dependency(
        ctx: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> AuthContext:
        if roles and ctx.role not in roles:
            raise Forbidden()
        return ctx

    return dependency
