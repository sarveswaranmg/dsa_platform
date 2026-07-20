"""Examiner JWT validation.

This service never issues tokens — it only validates access tokens minted by
the exam service. The claim contract (shared via JWT_SECRET, HS256):
sub (examiner id), org_id, role, type="examiner_access", jti, iat, exp.
"""

from typing import Any

import jwt

from app.core.config import get_settings
from app.core.exceptions import TokenInvalid

TOKEN_TYPE_EXAMINER_ACCESS = "examiner_access"


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["sub", "org_id", "role", "type", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenInvalid() from exc
    if payload["type"] != TOKEN_TYPE_EXAMINER_ACCESS:
        raise TokenInvalid()
    return payload
