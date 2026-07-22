"""Token-plane validation at the edge.

The gateway only decides *which plane may reach which route*. It passes the
token through untouched and every service re-validates it, so the gateway is a
filter and never the sole authority (architecture.md §6).
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from app.config import get_settings
from app.routing import Policy

TOKEN_TYPE_EXAMINER = "examiner_access"
TOKEN_TYPE_CANDIDATE = "candidate_exam"

_POLICY_TOKEN_TYPE = {
    Policy.EXAMINER: TOKEN_TYPE_EXAMINER,
    Policy.CANDIDATE: TOKEN_TYPE_CANDIDATE,
}


class AuthFailed(Exception):
    def __init__(self, detail: str = "Invalid or expired token") -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class Identity:
    """Who the rate limiter and logs attribute this request to."""

    kind: str  # "examiner" | "candidate" | "ip"
    value: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"


@lru_cache
def _public_key() -> RSAPublicKey:
    key = load_pem_public_key(get_settings().rs256_public_key.encode())
    assert isinstance(key, RSAPublicKey)
    return key


def _decode(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            _public_key(),
            algorithms=["RS256"],
            options={"require": ["sub", "type", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthFailed() from exc
    return payload


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def authorise(
    policy: Policy, authorization: str | None, client_ip: str
) -> Identity:
    """Enforce the route's plane and return the identity to rate-limit on."""
    if policy is Policy.PUBLIC:
        # Unauthenticated surface: attribute to the caller's address so a
        # login flood is bounded per source.
        return Identity("ip", client_ip)

    token = bearer_token(authorization)
    if token is None:
        raise AuthFailed("Missing bearer token")

    payload = _decode(token)
    expected = _POLICY_TOKEN_TYPE[policy]
    if payload.get("type") != expected:
        # A candidate token must never reach an examiner route, or vice versa.
        raise AuthFailed("Token is not valid for this route")

    kind = "examiner" if expected == TOKEN_TYPE_EXAMINER else "candidate"
    return Identity(kind, str(payload["sub"]))
