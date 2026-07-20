import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.exceptions import TokenInvalid
from app.models.examiner import Role

TOKEN_TYPE_EXAMINER_ACCESS = "examiner_access"
TOTP_ISSUER = "DSA Exam Platform"

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(
    *,
    examiner_id: uuid.UUID,
    org_id: uuid.UUID,
    role: Role,
    expires_in: int | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = settings.access_token_ttl_seconds if expires_in is None else expires_in
    payload = {
        "sub": str(examiner_id),
        "org_id": str(org_id),
        "role": role.value,
        "type": TOKEN_TYPE_EXAMINER_ACCESS,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


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


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)
