"""Examiner JWT validation.

This service never issues tokens — it only validates access tokens minted by
the exam service (RS256, verified with the public key only). The claim
contract: sub (examiner id), org_id, role, type="examiner_access", jti, iat,
exp.
"""

from functools import lru_cache
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from app.core.config import get_settings
from app.core.exceptions import TokenInvalid

TOKEN_TYPE_EXAMINER_ACCESS = "examiner_access"


@lru_cache
def _public_key() -> RSAPublicKey:
    key = load_pem_public_key(get_settings().rs256_public_key.encode())
    assert isinstance(key, RSAPublicKey)
    return key


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            _public_key(),
            algorithms=["RS256"],
            options={"require": ["sub", "org_id", "role", "type", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenInvalid() from exc
    if payload["type"] != TOKEN_TYPE_EXAMINER_ACCESS:
        raise TokenInvalid()
    return payload
