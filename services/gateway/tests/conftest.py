import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import Identity
from app.config import get_settings
from app.deps import get_forwarder, get_rate_limiter
from app.main import create_app
from app.routing import Upstream


class FakeForwarder:
    """Records the forwarded call and returns a canned upstream response — no
    real exam/question service needed."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = 200
        self.body = b'{"ok": true}'

    async def forward(
        self,
        *,
        upstream: Upstream,
        method: str,
        path: str,
        query: str,
        headers: dict[str, str],
        body: bytes,
    ) -> httpx.Response:
        self.calls.append(
            {
                "upstream": upstream,
                "method": method,
                "path": path,
                "query": query,
                "headers": headers,
                "body": body,
            }
        )
        return httpx.Response(self.status, content=self.body)


class CountingRateLimiter:
    """Deterministic limiter for tests: counts per identity, no Redis."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def check(self, identity: Identity, limit: int) -> int | None:
        key = str(identity)
        self.counts[key] = self.counts.get(key, 0) + 1
        return 30 if self.counts[key] > limit else None


@pytest.fixture
def forwarder() -> FakeForwarder:
    return FakeForwarder()


@pytest.fixture
def rate_limiter() -> CountingRateLimiter:
    return CountingRateLimiter()


@pytest.fixture
async def client(
    forwarder: FakeForwarder, rate_limiter: CountingRateLimiter
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_forwarder] = lambda: forwarder
    app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://gw") as http_client:
        yield http_client


def _token(token_type: str, sub: str | None = None) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub or str(uuid.uuid4()),
        "type": token_type,
        "exp": now + timedelta(minutes=15),
        "iat": now,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def examiner_headers(sub: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token('examiner_access', sub)}"}


def candidate_headers(sub: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token('candidate_exam', sub)}"}
