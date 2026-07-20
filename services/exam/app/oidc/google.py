from dataclasses import dataclass
from typing import Protocol

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from app.core.config import get_settings
from app.core.exceptions import OIDCError

GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


@dataclass(frozen=True)
class VerifiedIdentity:
    email: str
    email_verified: bool


class GoogleOIDCVerifier(Protocol):
    """Validates a Google ID token and returns the authenticated identity.
    Implementations must verify signature, issuer, and audience."""

    async def verify(self, id_token: str) -> VerifiedIdentity: ...


class JoseGoogleVerifier:
    def __init__(self, client_id: str) -> None:
        self._client_id = client_id

    async def verify(self, id_token: str) -> VerifiedIdentity:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                jwks = (await client.get(GOOGLE_JWKS_URI)).json()
        except httpx.HTTPError as exc:
            raise OIDCError("Could not reach Google to verify the token") from exc

        claims_registry = jwt.JWTClaimsRegistry(
            iss={"essential": True, "values": GOOGLE_ISSUERS},
            aud={"essential": True, "value": self._client_id},
            exp={"essential": True},
        )
        try:
            # RS256 only — never trust an unsigned or symmetric-alg token.
            token = jwt.decode(id_token, KeySet.import_key_set(jwks), algorithms=["RS256"])
            claims_registry.validate(token.claims)
        except (JoseError, ValueError) as exc:
            raise OIDCError() from exc

        email = token.claims.get("email")
        if not email:
            raise OIDCError("Google token has no email claim")
        return VerifiedIdentity(
            email=str(email),
            email_verified=bool(token.claims.get("email_verified", False)),
        )


def get_oidc_verifier() -> GoogleOIDCVerifier:
    # FastAPI dependency; overridden in tests with a fake (no Google network).
    return JoseGoogleVerifier(get_settings().google_client_id)
